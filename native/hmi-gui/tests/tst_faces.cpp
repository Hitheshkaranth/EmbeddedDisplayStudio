// tests/tst_faces.cpp -- the Phase 2 gate: every native face paints the same
// pixels as its Canvas twin.
//
// For each face in tests/native/fixtures/faces/<Name>.json, every case is
// rendered at every size through
//   ui/qml/Shadcn/faces/canvas/<Name>Face.qml   (the Canvas painter)
//   ui/qml/Shadcn/faces/native/<Name>Face.qml   (the C++ painter, Shadcn.Native)
// offscreen with the software scene graph, and the two images are compared:
//   diffFraction  share of pixels whose largest channel difference is > 48
//   meanDiff      mean absolute channel difference over the whole image
// Both must stay under the fixture's maxDiffFraction / maxMeanDiff. Faces
// whose implemented() is false (the stubs) are skipped, not failed.
//
// Set HMI_FACES_OUT=<dir> to also write <Name>-<case>-<w>x<h>-{canvas,native,
// diff}.png for eyeballing. Set HMI_FACES=Name1,Name2 to restrict the run.
//
// wrapperUsesNativeFace loads each Sh<Name>.qml widget with the module
// registered and checks that Theme.nativeFaces is true and that a FaceItem
// ended up in the tree with a non-empty spec, i.e. the Loader switch works.

#include "faces/faceitem.h"
#include "faces/nativefaces.h"

#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainterPath>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickView>
#include <QtTest>

#ifndef HMI_REPO_ROOT
#error "HMI_REPO_ROOT must be defined (tests/CMakeLists.txt does it)"
#endif

namespace {

const QString kRepo = QStringLiteral(HMI_REPO_ROOT);
const QString kKit = kRepo + QStringLiteral("/ui/qml/Shadcn");
const QString kFixtures = kRepo + QStringLiteral("/tests/native/fixtures/faces");
const QColor kBackground(QStringLiteral("#101318"));

// Exposes the protected static helpers for arcHelpers().
struct HelperProbe : hmi::FaceItem {
    using FaceItem::arc;
    using FaceItem::arcTo;
    void paintFace(QPainter *, const QVariantMap &) override {}
};

// JSON -> spec map. Colour strings ("#rrggbb" / "#aarrggbb") become QColor,
// as the wrapper widgets pass real colours, so the Canvas painter can read
// s.colour.r and the C++ one gets a QColor variant.
QVariant fromJson(const QJsonValue &v)
{
    switch (v.type()) {
    case QJsonValue::String: {
        const QString s = v.toString();
        if (s.startsWith(QLatin1Char('#'))) {
            const QColor c(s);
            if (c.isValid())
                return QVariant::fromValue(c);
        }
        return s;
    }
    case QJsonValue::Array: {
        QVariantList out;
        for (const QJsonValue &e : v.toArray())
            out << fromJson(e);
        return out;
    }
    case QJsonValue::Object: {
        QVariantMap out;
        const QJsonObject o = v.toObject();
        for (auto it = o.begin(); it != o.end(); ++it)
            out.insert(it.key(), fromJson(it.value()));
        return out;
    }
    default:
        return v.toVariant();
    }
}

struct Rendered {
    QImage image;
    QString error;
    hmi::FaceItem *face = nullptr;   // the native item, when the source is one
};

// Renders one face file at `size` with `spec`, waiting until two consecutive
// grabs agree (the Canvas paints on a later frame than the C++ item).
Rendered render(const QString &qmlPath, const QVariantMap &spec, const QSize &size)
{
    Rendered r;
    QQuickView view;
    view.setColor(kBackground);
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.resize(size);
    view.setSource(QUrl::fromLocalFile(qmlPath));
    if (view.status() != QQuickView::Ready) {
        for (const QQmlError &e : view.errors())
            r.error += e.toString() + QLatin1Char('\n');
        if (r.error.isEmpty())
            r.error = QStringLiteral("status %1").arg(int(view.status()));
        return r;
    }
    QQuickItem *root = view.rootObject();
    root->setProperty("spec", QVariant::fromValue(spec));
    r.face = qobject_cast<hmi::FaceItem *>(root);
    view.show();

    QImage prev;
    int stable = 0;
    QElapsedTimer t;
    t.start();
    while (t.elapsed() < 4000) {
        QTest::qWait(25);
        QImage img = view.grabWindow();
        if (!prev.isNull() && img == prev) {
            if (++stable >= 3) {
                r.image = img;
                break;
            }
        } else {
            stable = 0;
        }
        prev = img;
    }
    if (r.image.isNull())
        r.image = prev;
    r.image = r.image.convertToFormat(QImage::Format_ARGB32);
    r.face = nullptr;   // the view (and the item) die with this scope
    return r;
}

struct Diff {
    double fraction = 1.0;
    double mean = 255.0;
    QImage map;
};

Diff compare(const QImage &a, const QImage &b)
{
    Diff d;
    if (a.size() != b.size() || a.isNull())
        return d;
    d.map = QImage(a.size(), QImage::Format_ARGB32);
    d.map.fill(Qt::black);
    qint64 sum = 0, big = 0;
    for (int y = 0; y < a.height(); ++y) {
        const QRgb *pa = reinterpret_cast<const QRgb *>(a.constScanLine(y));
        const QRgb *pb = reinterpret_cast<const QRgb *>(b.constScanLine(y));
        QRgb *pm = reinterpret_cast<QRgb *>(d.map.scanLine(y));
        for (int x = 0; x < a.width(); ++x) {
            const int dr = std::abs(qRed(pa[x]) - qRed(pb[x]));
            const int dg = std::abs(qGreen(pa[x]) - qGreen(pb[x]));
            const int db = std::abs(qBlue(pa[x]) - qBlue(pb[x]));
            const int mx = std::max(dr, std::max(dg, db));
            sum += dr + dg + db;
            if (mx > 48) {
                ++big;
                pm[x] = qRgb(255, 0, 0);
            } else if (mx > 0) {
                pm[x] = qRgb(mx * 4, mx * 4, 0);
            }
        }
    }
    const double n = double(a.width()) * a.height();
    d.fraction = big / n;
    d.mean = sum / (3.0 * n);
    return d;
}

QStringList selectedFaces()
{
    const QString sel = qEnvironmentVariable("HMI_FACES");
    if (sel.trimmed().isEmpty())
        return hmi::nativeFaceNames();
    return sel.split(QLatin1Char(','), Qt::SkipEmptyParts);
}

QQuickItem *findFace(QQuickItem *item)
{
    if (auto *f = qobject_cast<hmi::FaceItem *>(item))
        return f;
    const auto kids = item->childItems();
    for (QQuickItem *k : kids)
        if (QQuickItem *f = findFace(k))
            return f;
    return nullptr;
}

} // namespace

class TstFaces : public QObject
{
    Q_OBJECT

private slots:
    void initTestCase()
    {
        QVERIFY2(QFileInfo::exists(kKit + QStringLiteral("/qmldir")),
                 qPrintable(QStringLiteral("kit not found at ") + kKit));
        QVERIFY2(QDir(kFixtures).exists(), qPrintable(QStringLiteral("fixtures not found at ") + kFixtures));
        hmi::registerNativeFaces();
    }

    // The Canvas-2D arc helpers are the foundation every face is built on.
    void arcHelpers()
    {
        // ctx.arc on an empty path starts at the arc start (no line from 0,0).
        QPainterPath p;
        HelperProbe::arc(p, 50, 50, 40, 0, M_PI / 2);          // right -> bottom, clockwise on screen
        QCOMPARE(p.elementCount() > 1, true);
        QCOMPARE(p.elementAt(0).type, QPainterPath::MoveToElement);
        QVERIFY(qAbs(p.elementAt(0).x - 90) < 1e-6 && qAbs(p.elementAt(0).y - 50) < 1e-6);
        QVERIFY((p.currentPosition() - QPointF(50, 90)).manhattanLength() < 1e-6);
        // Midpoint of the sweep lies at 45 degrees below-right (y down).
        const QPointF mid = p.pointAtPercent(0.5);
        QVERIFY(mid.x() > 50 && mid.y() > 50);

        // Full circle when the sweep reaches 2*pi.
        QPainterPath c;
        HelperProbe::arc(c, 50, 50, 10, 0, 2 * M_PI);
        QVERIFY(c.contains(QPointF(50, 50)));
        QVERIFY(c.contains(QPointF(41, 50)) && c.contains(QPointF(50, 59)));

        // Anticlockwise: from 0 to -pi/2 anticlockwise goes up on screen.
        QPainterPath a;
        HelperProbe::arc(a, 50, 50, 40, 0, -M_PI / 2, true);
        QVERIFY((a.currentPosition() - QPointF(50, 10)).manhattanLength() < 1e-6);
        QVERIFY(a.pointAtPercent(0.5).y() < 50);

        // arcTo rounded rectangle 0,0..100,100 radius 20 (VehicleStatus body).
        QPainterPath rr;
        rr.moveTo(20, 0);
        rr.lineTo(80, 0);
        HelperProbe::arcTo(rr, 100, 0, 100, 20, 20);
        rr.lineTo(100, 80);
        HelperProbe::arcTo(rr, 100, 100, 80, 100, 20);
        rr.lineTo(20, 100);
        HelperProbe::arcTo(rr, 0, 100, 0, 80, 20);
        rr.lineTo(0, 20);
        HelperProbe::arcTo(rr, 0, 0, 20, 0, 20);
        rr.closeSubpath();
        QVERIFY(rr.contains(QPointF(50, 50)));
        QVERIFY(rr.contains(QPointF(2, 50)));
        QVERIFY(rr.contains(QPointF(50, 98)));
        QVERIFY(!rr.contains(QPointF(1, 1)));
        QVERIFY(!rr.contains(QPointF(99, 99)));
        QVERIFY(!rr.contains(QPointF(2, 98)));
        QVERIFY(rr.contains(QPointF(6, 6)));      // inside the corner arc
        QVERIFY(!rr.contains(QPointF(2.5, 2.5))); // outside it
        const QRectF bb = rr.boundingRect();
        QVERIFY(qAbs(bb.left()) < 1e-6 && qAbs(bb.top()) < 1e-6);
        QVERIFY(qAbs(bb.right() - 100) < 1e-6 && qAbs(bb.bottom() - 100) < 1e-6);
    }

    void everyFaceHasBothQmlFiles()
    {
        for (const QString &name : hmi::nativeFaceNames()) {
            QVERIFY2(QFileInfo::exists(kKit + QStringLiteral("/faces/canvas/%1Face.qml").arg(name)),
                     qPrintable(name + QStringLiteral(": canvas face missing")));
            QVERIFY2(QFileInfo::exists(kKit + QStringLiteral("/faces/native/%1Face.qml").arg(name)),
                     qPrintable(name + QStringLiteral(": native face missing")));
            QVERIFY2(QFileInfo::exists(kFixtures + QStringLiteral("/%1.json").arg(name)),
                     qPrintable(name + QStringLiteral(": fixture missing")));
        }
    }

    void wrapperUsesNativeFace_data()
    {
        QTest::addColumn<QString>("name");
        for (const QString &name : hmi::nativeFaceNames())
            QTest::newRow(qPrintable(name)) << name;
    }

    void wrapperUsesNativeFace()
    {
        QFETCH(QString, name);
        QQmlEngine engine;
        engine.addImportPath(kRepo + QStringLiteral("/ui/qml"));
        QQmlComponent component(&engine);
        const QString src = QStringLiteral(
            "import QtQuick 2.15\nimport Shadcn 1.0\n"
            "Item { width: 240; height: 240\n"
            "  property bool nativeFaces: Theme.nativeFaces\n"
            "  Sh%1 { anchors.fill: parent }\n}\n").arg(name);
        component.setData(src.toUtf8(), QUrl::fromLocalFile(kRepo + QStringLiteral("/tests/faces-wrapper.qml")));
        QVERIFY2(!component.isError(), qPrintable(component.errorString()));
        QScopedPointer<QObject> obj(component.create());
        QVERIFY2(obj, qPrintable(component.errorString()));
        QCOMPARE(obj->property("nativeFaces").toBool(), true);
        auto *root = qobject_cast<QQuickItem *>(obj.data());
        QVERIFY(root);
        QQuickItem *face = findFace(root);
        QVERIFY2(face, "no FaceItem in the widget tree: the Loader did not pick the native face");
        // QML wraps the type in a dynamic meta-object ("XFace_QMLTYPE_n"), so
        // check the inheritance chain rather than the class name.
        QVERIFY2(face->inherits(qPrintable(QStringLiteral("hmi::%1Face").arg(name))),
                 qPrintable(QStringLiteral("face is %1, not hmi::%2Face")
                                .arg(QString::fromLatin1(face->metaObject()->className()), name)));
        const QVariantMap spec = face->property("spec").toMap();
        QVERIFY2(!spec.isEmpty(), "the wrapper's spec binding did not reach the face");
    }

    void matchesCanvas_data()
    {
        QTest::addColumn<QString>("name");
        QTest::addColumn<QString>("caseName");
        QTest::addColumn<QSize>("size");
        QTest::addColumn<QVariantMap>("spec");
        QTest::addColumn<double>("maxFraction");
        QTest::addColumn<double>("maxMean");

        for (const QString &name : selectedFaces()) {
            QFile f(kFixtures + QStringLiteral("/%1.json").arg(name));
            if (!f.open(QIODevice::ReadOnly))
                continue;
            const QJsonObject doc = QJsonDocument::fromJson(f.readAll()).object();
            const double maxFraction = doc.value(QStringLiteral("maxDiffFraction")).toDouble(0.02);
            const double maxMean = doc.value(QStringLiteral("maxMeanDiff")).toDouble(1.5);
            QList<QSize> sizes;
            for (const QJsonValue &s : doc.value(QStringLiteral("sizes")).toArray())
                sizes << QSize(s.toArray().at(0).toInt(), s.toArray().at(1).toInt());
            const QJsonObject cases = doc.value(QStringLiteral("cases")).toObject();
            for (auto it = cases.begin(); it != cases.end(); ++it) {
                QJsonObject spec = it.value().toObject();
                QList<QSize> caseSizes = sizes;
                if (spec.contains(QStringLiteral("size"))) {   // a case may pin its own size
                    const QJsonArray s = spec.take(QStringLiteral("size")).toArray();
                    caseSizes = {QSize(s.at(0).toInt(), s.at(1).toInt())};
                }
                for (const QSize &size : caseSizes) {
                    const QString tag = QStringLiteral("%1/%2 %3x%4").arg(name, it.key()).arg(size.width()).arg(size.height());
                    QTest::newRow(qPrintable(tag)) << name << it.key() << size
                                                   << fromJson(spec).toMap() << maxFraction << maxMean;
                }
            }
        }
    }

    void matchesCanvas()
    {
        QFETCH(QString, name);
        QFETCH(QString, caseName);
        QFETCH(QSize, size);
        QFETCH(QVariantMap, spec);
        QFETCH(double, maxFraction);
        QFETCH(double, maxMean);

        // Skip the stubs: a face reports implemented() == false until ported.
        {
            QQmlEngine engine;
            QQmlComponent probe(&engine);
            probe.setData(QStringLiteral("import Shadcn.Native 1.0\n%1Face {}\n").arg(name).toUtf8(), QUrl());
            QScopedPointer<QObject> obj(probe.create());
            QVERIFY2(obj, qPrintable(probe.errorString()));
            auto *face = qobject_cast<hmi::FaceItem *>(obj.data());
            QVERIFY(face);
            if (!face->implemented())
                QSKIP("face not implemented yet (stub)");
        }

        const Rendered canvas = render(kKit + QStringLiteral("/faces/canvas/%1Face.qml").arg(name), spec, size);
        QVERIFY2(canvas.error.isEmpty(), qPrintable(canvas.error));
        const Rendered native = render(kKit + QStringLiteral("/faces/native/%1Face.qml").arg(name), spec, size);
        QVERIFY2(native.error.isEmpty(), qPrintable(native.error));
        QCOMPARE(native.image.size(), canvas.image.size());

        const Diff d = compare(canvas.image, native.image);
        const QString outDir = qEnvironmentVariable("HMI_FACES_OUT");
        if (!outDir.isEmpty()) {
            QDir().mkpath(outDir);
            const QString base = QStringLiteral("%1/%2-%3-%4x%5-").arg(outDir, name, caseName)
                                     .arg(size.width()).arg(size.height());
            canvas.image.save(base + QStringLiteral("canvas.png"));
            native.image.save(base + QStringLiteral("native.png"));
            d.map.save(base + QStringLiteral("diff.png"));
        }
        qInfo().noquote() << QStringLiteral("%1/%2 %3x%4: diffFraction %5 meanDiff %6")
                                 .arg(name, caseName).arg(size.width()).arg(size.height())
                                 .arg(d.fraction, 0, 'f', 4).arg(d.mean, 0, 'f', 2);
        QVERIFY2(d.fraction <= maxFraction,
                 qPrintable(QStringLiteral("%1 of pixels differ by > 48 (limit %2)").arg(d.fraction).arg(maxFraction)));
        QVERIFY2(d.mean <= maxMean,
                 qPrintable(QStringLiteral("mean channel difference %1 (limit %2)").arg(d.mean).arg(maxMean)));
    }
};

QTEST_MAIN(TstFaces)
#include "tst_faces.moc"
