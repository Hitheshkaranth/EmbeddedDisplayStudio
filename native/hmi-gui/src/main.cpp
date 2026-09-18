// native/hmi-gui/src/main.cpp
// Layer: 2 (GUI Loader)
// Purpose: entry point. Port of main() in gui/hmi_loader/main.py: parses the
// same flags, sets up the QML engine and import paths, validates the bundle,
// exposes Tags / Bus / BusImpl / Hmi, loads the shell.
//
// CLI (frozen -- hmi-gui-launch, hmi-install and the smoke tests pass these):
//   --apps-dir DIR      bundle directory            (default /opt/hmi_apps/current)
//   --shell FILE        custom shell QML            (default <exe>/../shell/Shell.qml)
//   --rx-port N         telemetry receive port      (default 5001)
//   --daemon-host HOST  hardware daemon address     (default 127.0.0.1)
//   --daemon-port N     hardware daemon port        (default 5000)
//   --ready-file FILE   readiness marker            (default /run/hmi/gui-ready)
//   --windowed          run windowed for desktop development
//   --theme light|dark  initial theme (default: the manifest's, else dark)
//   --exit-after MS     hidden; quit after MS milliseconds (smoke tests)
//   --log-level L       DEBUG|INFO|WARNING|ERROR    (default INFO)
//
// Path resolution (CONTRACT section 3), mirroring main.py:
//   QML import paths: <repo>/ui/qml when running from a checkout (found by
//   walking up from the executable looking for ui/qml/Shadcn/qmldir), and
//   always /usr/lib/hmi/qml. Shell default: /usr/lib/hmi/shell/Shell.qml on
//   the panel, <repo>/gui/shell/Shell.qml from a checkout.
//
// Owner: W3. The flag set is frozen; the body may be refined.

#include "busshim.h"
#include "hmi.h"
#include "log.h"
#include "manifest.h"
#include "tagengine.h"

#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QTimer>
#include <QUrl>

#include <cstdio>

namespace {

// Walks up from `start` looking for a repository checkout (ui/qml/Shadcn/qmldir).
// Returns the repo root or an empty string.
QString findRepoRoot(const QString &start)
{
    QDir dir(start);
    for (int i = 0; i < 8; ++i) {
        if (QFileInfo::exists(dir.filePath(QStringLiteral("ui/qml/Shadcn/qmldir"))))
            return dir.absolutePath();
        if (!dir.cdUp())
            break;
    }
    return QString();
}

} // namespace

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("hmi-gui"));
    QCoreApplication::setApplicationVersion(QStringLiteral("2.0.0"));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("HMI GUI Loader (Layer 2)"));
    parser.addHelpOption();
    parser.addVersionOption();
    QCommandLineOption optAppsDir({QStringLiteral("apps-dir")}, QStringLiteral("Path to the app bundle"),
                                  QStringLiteral("DIR"), QStringLiteral("/opt/hmi_apps/current"));
    QCommandLineOption optShell({QStringLiteral("shell")}, QStringLiteral("Path to custom shell QML"),
                                QStringLiteral("FILE"));
    QCommandLineOption optRxPort({QStringLiteral("rx-port")}, QStringLiteral("Telemetry receive port"),
                                 QStringLiteral("N"), QStringLiteral("5001"));
    QCommandLineOption optDaemonHost({QStringLiteral("daemon-host")}, QStringLiteral("Hardware daemon host"),
                                     QStringLiteral("HOST"), QStringLiteral("127.0.0.1"));
    QCommandLineOption optDaemonPort({QStringLiteral("daemon-port")}, QStringLiteral("Hardware daemon port"),
                                     QStringLiteral("N"), QStringLiteral("5000"));
    QCommandLineOption optReadyFile({QStringLiteral("ready-file")}, QStringLiteral("Readiness marker file"),
                                    QStringLiteral("FILE"), QStringLiteral("/run/hmi/gui-ready"));
    QCommandLineOption optWindowed({QStringLiteral("windowed")}, QStringLiteral("Run windowed for desktop dev"));
    QCommandLineOption optTheme({QStringLiteral("theme")},
                                QStringLiteral("Initial theme (default: the manifest's, else dark)"),
                                QStringLiteral("light|dark"));
    QCommandLineOption optExitAfter({QStringLiteral("exit-after")}, QStringLiteral("Quit after N ms"),
                                    QStringLiteral("MS"));
    optExitAfter.setFlags(QCommandLineOption::HiddenFromHelp);
    QCommandLineOption optLogLevel({QStringLiteral("log-level")}, QStringLiteral("DEBUG|INFO|WARNING|ERROR"),
                                   QStringLiteral("LEVEL"), QStringLiteral("INFO"));
    parser.addOptions({optAppsDir, optShell, optRxPort, optDaemonHost, optDaemonPort, optReadyFile,
                       optWindowed, optTheme, optExitAfter, optLogLevel});
    parser.process(app);

    hmi::installLogging(parser.value(optLogLevel));

    const QString exeDir = QCoreApplication::applicationDirPath();
    const QString repoRoot = findRepoRoot(exeDir);

    QQmlApplicationEngine engine;
    if (!repoRoot.isEmpty())
        engine.addImportPath(QDir(repoRoot).filePath(QStringLiteral("ui/qml")));
    engine.addImportPath(QStringLiteral("/usr/lib/hmi/qml"));

    const QString appsDir = QFileInfo(parser.value(optAppsDir)).absoluteFilePath();
    const hmi::Manifest manifest = hmi::loadManifest(QDir(appsDir).filePath(QStringLiteral("manifest.json")));
    if (!manifest.valid)
        qCCritical(lcHmi).noquote() << manifest.error;

    hmi::TagEngine::Options options;
    options.rxPort = static_cast<quint16>(parser.value(optRxPort).toUInt());
    options.daemonHost = parser.value(optDaemonHost);
    options.daemonPort = static_cast<quint16>(parser.value(optDaemonPort).toUInt());

    auto *tagEngine = new hmi::TagEngine(manifest.expectedTags(), manifest.alarms(), options, &app);
    auto *hmiObj = new hmi::Hmi(manifest, appsDir, parser.value(optReadyFile), &app);
    if (!manifest.valid)
        hmiObj->setLastError(manifest.error);

    QQmlContext *ctx = engine.rootContext();
    hmi::exposeToQml(&engine, ctx, tagEngine);
    ctx->setContextProperty(QStringLiteral("Hmi"), hmiObj);
    ctx->setContextProperty(QStringLiteral("isWindowed"), parser.isSet(optWindowed));
    ctx->setContextProperty(QStringLiteral("initialTheme"),
                            hmi::resolveTheme(manifest, parser.value(optTheme)));

    QString shell = parser.value(optShell);
    if (shell.isEmpty()) {
        // Panel layout: /usr/lib/hmi/gui/hmi-gui -> /usr/lib/hmi/shell/Shell.qml.
        // Checkout layout: <repo>/gui/shell/Shell.qml.
        const QString panelShell = QDir(exeDir).filePath(QStringLiteral("../shell/Shell.qml"));
        if (QFileInfo::exists(panelShell))
            shell = QFileInfo(panelShell).absoluteFilePath();
        else if (!repoRoot.isEmpty())
            shell = QDir(repoRoot).filePath(QStringLiteral("gui/shell/Shell.qml"));
        else
            shell = QStringLiteral("/usr/lib/hmi/shell/Shell.qml");
    }

    engine.load(QUrl::fromLocalFile(shell));
    if (engine.rootObjects().isEmpty()) {
        qCCritical(lcHmi) << "Failed to load shell QML. Exiting.";
        return 1;
    }

    if (parser.isSet(optExitAfter)) {
        const int ms = parser.value(optExitAfter).toInt();
        QTimer::singleShot(ms, &app, &QCoreApplication::quit);
    }

    return app.exec();
}
