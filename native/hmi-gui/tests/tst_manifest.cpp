// native/hmi-gui/tests/tst_manifest.cpp
// QTest case for Manifest. The first test is a sanity check that proves the
// harness runs; the owner replaces the TODO with the real cases.
#include "manifest.h"

#include <QtTest>

class TstManifest : public QObject {
    Q_OBJECT
private slots:
    void missingFileIsReported()
    {
        const hmi::Manifest m = hmi::loadManifest(QStringLiteral("/nonexistent/manifest.json"));
        QVERIFY(!m.valid);
        QVERIFY(m.error.startsWith(QStringLiteral("Manifest not found: ")));
        QCOMPARE(m.name(), QStringLiteral("Error"));
    }
    // TODO(W3): every error string, defaults, theme resolution, alarmTags,
    // expectedTags ordering, apps/demo-app loads valid.
};

QTEST_GUILESS_MAIN(TstManifest)
#include "tst_manifest.moc"
