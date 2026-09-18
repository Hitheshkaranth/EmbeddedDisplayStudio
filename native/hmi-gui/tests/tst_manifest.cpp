// native/hmi-gui/tests/tst_manifest.cpp
// QTest case for Manifest validation and accessor methods.
#include "manifest.h"

#include <QFileInfo>
#include <QTemporaryDir>
#include <QTest>

class TstManifest : public QObject {
    Q_OBJECT

private slots:
    // -----------------------------------------------------------------------
    // Error strings
    // -----------------------------------------------------------------------
    void missingFileIsReported()
    {
        const hmi::Manifest m = hmi::loadManifest(QStringLiteral("/nonexistent/manifest.json"));
        QVERIFY(!m.valid);
        QVERIFY(m.error.startsWith(QStringLiteral("Manifest not found: ")));
        QCOMPARE(m.name(), QStringLiteral("Error"));
        QCOMPARE(m.version(), QStringLiteral("0.0.0"));
        QCOMPARE(m.screenWidth(), 1280);
        QCOMPARE(m.screenHeight(), 800);
        QCOMPARE(m.tagsRequired(), QStringList());
        QCOMPARE(m.alarms(), QVariantList());
        QCOMPARE(m.alarmTags(), QStringList());
        QCOMPARE(m.expectedTags(), QStringList());
        QCOMPARE(m.data, QVariantMap());
    }

    void parseErrorOnBadJson()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{bad json [[[");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QVERIFY(m.error.startsWith(QStringLiteral("Manifest parse error: ")));
        QCOMPARE(m.data, QVariantMap());
    }

    void parseErrorOnNonObject()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("[1, 2, 3]");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QVERIFY(m.error.startsWith(QStringLiteral("Manifest parse error: ")));
    }

    void schemaStringRejected()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        QString entry = "main.qml";
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":\"1\",\"name\":\"test\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error, QStringLiteral("Unsupported or missing schema version. Expected schema: 1."));
    }

    void schemaMissingRejected()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        QString entry = "main.qml";
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"name\":\"test\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error, QStringLiteral("Unsupported or missing schema version. Expected schema: 1."));
    }

    void invalidAppName()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"BAD\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error, QStringLiteral("Invalid app name: 'BAD'. Must match ^[a-z0-9][a-z0-9._-]{0,63}$"));
    }

    void invalidAppNameEmpty()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error,
                 QStringLiteral("Invalid app name: ''. Must match ^[a-z0-9][a-z0-9._-]{0,63}$"));
    }

    void invalidAppNameMissing()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error,
                 QStringLiteral("Invalid app name: ''. Must match ^[a-z0-9][a-z0-9._-]{0,63}$"));
    }

    void missingEntry()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\"}");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error, QStringLiteral("Missing 'entry' in manifest."));
    }

    void entryContainsDotDot()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"../x/main.qml\"}");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error,
                 QStringLiteral("Invalid entry path: '../x/main.qml'. Cannot be absolute or contain '..'."));
    }

    void entryAbsolute()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"/etc/passwd\"}");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QCOMPARE(m.error,
                 QStringLiteral("Invalid entry path: '/etc/passwd'. Cannot be absolute or contain '..'."));
    }

    void entryPointNotFound()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\"}");
            f.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(!m.valid);
        QVERIFY(m.error.startsWith(QStringLiteral("Entry point not found: ")));
        QVERIFY(m.error.contains("main.qml"));
    }

    // -----------------------------------------------------------------------
    // Valid minimal manifest
    // -----------------------------------------------------------------------
    void validMinimalManifest()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(m.error, QString());
        QCOMPARE(m.path, path);
        QCOMPARE(m.name(), QStringLiteral("test"));
        QCOMPARE(m.version(), QStringLiteral("0.0.0"));
        QCOMPARE(m.entry(), QStringLiteral("main.qml"));
        QCOMPARE(m.screenWidth(), 1280);
        QCOMPARE(m.screenHeight(), 800);
        QCOMPARE(m.theme(), QString());
        QCOMPARE(m.tagsRequired(), QStringList());
        QCOMPARE(m.alarms(), QVariantList());
        QCOMPARE(m.alarmTags(), QStringList());
        QCOMPARE(m.expectedTags(), QStringList());
    }

    // -----------------------------------------------------------------------
    // Accessors with full data
    // -----------------------------------------------------------------------
    void accessorsFullManifest()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            QString fullJson = "{\"schema\":1,\"name\":\"my.app\",\"version\":\"2.1.0\","
                    "\"entry\":\"app.qml\",\"screen\":{\"width\":1920,\"height\":1080},"
                    "\"theme\":\"light\","
                    "\"tags_required\":[\"ai.press\",\"di.valve\"],"
                    "\"alarms\":[{\"tag\":\"ai.press\",\"label\":\"Press\",\"unit\":\"kPa\"},"
                    "42,\"not-a-map\"]}";
            f.write(fullJson.toUtf8());
            f.close();
        }
        {
            QFile e(dir.filePath("app.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(m.name(), QStringLiteral("my.app"));
        QCOMPARE(m.version(), QStringLiteral("2.1.0"));
        QCOMPARE(m.screenWidth(), 1920);
        QCOMPARE(m.screenHeight(), 1080);
        QCOMPARE(m.theme(), QStringLiteral("light"));
        QStringList tr; tr << "ai.press" << "di.valve";
        QCOMPARE(m.tagsRequired(), tr);
        QCOMPARE(m.alarms().size(), 3);
        QStringList atags; atags << "ai.press";
        QCOMPARE(m.alarmTags(), atags);
        QStringList et; et << "ai.press" << "di.valve";
        QCOMPARE(m.expectedTags(), et);
    }

    void themeBlueReturnsEmpty()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\",\"theme\":\"blue\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(m.theme(), QString());
    }

    // -----------------------------------------------------------------------
    // resolveTheme
    // -----------------------------------------------------------------------
    void resolveThemeOverrideWins()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\",\"theme\":\"dark\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(hmi::resolveTheme(m, QStringLiteral("light")), QStringLiteral("light"));
    }

    void resolveThemeFromManifest()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\",\"theme\":\"dark\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(hmi::resolveTheme(m, QString()), QStringLiteral("dark"));
    }

    void resolveThemeDefaultDark()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\"}");
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QCOMPARE(hmi::resolveTheme(m, QString()), QStringLiteral("dark"));
    }

    // -----------------------------------------------------------------------
    // alarmTags dedup and order
    // -----------------------------------------------------------------------
void alarmTagsDedupe()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            QString fullJson = "{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\","
                    "\"alarms\":[{\"tag\":\"a\",\"label\":\"A\"},"
                    "{\"tag\":\"b\",\"label\":\"B\"},"
                    "{\"tag\":\"a\",\"label\":\"A again\"},"
                    "5,\"not-a-map\"]}";
            f.write(fullJson.toUtf8());
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QStringList atags; atags << "a" << "b";
        QCOMPARE(m.alarmTags(), atags);
    }

    // -----------------------------------------------------------------------
    // expectedTags order
    // -----------------------------------------------------------------------
    void expectedTagsOrder()
    {
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        QString path = dir.filePath("manifest.json");
        {
            QFile f(path);
            QVERIFY(f.open(QIODevice::WriteOnly));
            QString fullJson = "{\"schema\":1,\"name\":\"test\",\"entry\":\"main.qml\","
                    "\"tags_required\":[\"b\",\"c\"],"
                    "\"alarms\":[{\"tag\":\"a\",\"label\":\"A\"},"
                    "{\"tag\":\"b\",\"label\":\"B\"}]"
                    "}";
            f.write(fullJson.toUtf8());
            f.close();
        }
        {
            QFile e(dir.filePath("main.qml"));
            QVERIFY(e.open(QIODevice::WriteOnly));
            e.write(" ");
            e.close();
        }
        const hmi::Manifest m = hmi::loadManifest(path);
        QVERIFY(m.valid);
        QStringList et; et << "b" << "c" << "a";
        QCOMPARE(m.expectedTags(), et);
    }

    // -----------------------------------------------------------------------
    // Real bundle: apps/demo-app (find repo root from __FILE__)
    // -----------------------------------------------------------------------
    void realDemoApp()
    {
        // __FILE__ is the path to this .cpp file
        QString srcDir = QFileInfo(__FILE__).absolutePath();
        // srcDir = .../native/hmi-gui/tests  (or build dir equivalent)
        // Go up 3 levels to get the repo root
        QString repoRoot = srcDir;
        for (int i = 0; i < 3; ++i) {
            QDir d(repoRoot);
            if (d.cdUp())
                repoRoot = d.absolutePath();
        }
        QString manifestPath = QDir(repoRoot).filePath(QStringLiteral("apps/demo-app/manifest.json"));
        const hmi::Manifest m = hmi::loadManifest(manifestPath);
        QVERIFY(m.valid);
        QCOMPARE(m.name(), QStringLiteral("demo-app"));
        QCOMPARE(m.version(), QStringLiteral("1.0.0"));
        QCOMPARE(m.entry(), QStringLiteral("main.qml"));
        QCOMPARE(m.screenWidth(), 1280);
        QCOMPARE(m.screenHeight(), 800);
        QCOMPARE(m.theme(), QString());
        QStringList tr; tr << "ai.pot" << "di.estop" << "do.relay1";
        QCOMPARE(m.tagsRequired(), tr);
    }

    // -----------------------------------------------------------------------
    // Real bundle: tests/native/fixtures/probe-app
    // -----------------------------------------------------------------------
    void realProbeApp()
    {
        QString srcDir = QFileInfo(__FILE__).absolutePath();
        QString repoRoot = srcDir;
        for (int i = 0; i < 3; ++i) {
            QDir d(repoRoot);
            if (d.cdUp())
                repoRoot = d.absolutePath();
        }
        QString manifestPath = QDir(repoRoot).filePath(
            QStringLiteral("tests/native/fixtures/probe-app/manifest.json"));
        const hmi::Manifest m = hmi::loadManifest(manifestPath);
        QVERIFY(m.valid);
        QCOMPARE(m.name(), QStringLiteral("probe-app"));
        QCOMPARE(m.version(), QStringLiteral("1.0.0"));
        QCOMPARE(m.screenWidth(), 640);
        QCOMPARE(m.screenHeight(), 480);
        QCOMPARE(m.theme(), QStringLiteral("light"));
        QStringList tr; tr << "ai.pot" << "di.estop" << "do.relay1";
        QCOMPARE(m.tagsRequired(), tr);
        QStringList atags; atags << "ai.pot";
        QCOMPARE(m.alarmTags(), atags);
        QStringList et; et << "ai.pot" << "di.estop" << "do.relay1";
        QCOMPARE(m.expectedTags(), et);
    }
};

QTEST_GUILESS_MAIN(TstManifest)
#include "tst_manifest.moc"