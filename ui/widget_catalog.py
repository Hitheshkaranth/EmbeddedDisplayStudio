"""Render every Studio widget at its registered size for visual review.

python -m ui.widget_catalog --output .tmp/widget-catalog
Produces category contact sheets, individual captures and a QML error report.
"""
import argparse
import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from designer.generators.qml_generator import QmlGenerator
from designer.model import DesignerWidget
from designer.palette.widget_registry import default_registry
from ui.python.shadcn import color

SAMPLES = {
    'ShSlider': {'label': 'Pump speed', 'value': 42, 'unit': '%'},
    'ShToggle': {'label': 'Auto mode', 'checked': True},
    'ShCheckbox': {'label': 'Enable interlock', 'checked': True},
    'ShNumInput': {'label': 'Pressure setpoint', 'value': 42, 'unit': 'bar'},
    'ShNumDisplay': {'label': 'Line pressure', 'value': 42.6, 'unit': 'bar'},
    'ShAnalogDisplay': {'label': 'Tank level', 'value': 64, 'unit': '%'},
    'ShTrendChart': {'label': 'Supply pressure', 'unit': 'bar', 'data': [35, 39, 44, 41, 52, 58]},
    'ShAlarmTable': {'alarms': [
        {'severity': 'fault', 'message': 'System overheat', 'timestamp': '12:04', 'acknowledged': False},
        {'severity': 'warning', 'message': 'High pressure', 'timestamp': '12:03', 'acknowledged': True},
    ]},
    'ShValueTile': {'title': 'Input voltage', 'value': '24.8', 'unit': 'V', 'state': 'ok'},
    'ShGauge': {'value': 42, 'label': 'Pump speed', 'unit': '%'},
}


IGNORED_WARNING_PARTS = (
    'Cannot find font directory',
    'Qt no longer ships fonts',
    'data property has already been assigned',
    'Member data of the object ShTrendChart',
)


def capture(output, samples=False):
    app = QApplication.instance() or QApplication([])
    registry = default_registry()
    generator = QmlGenerator(registry)
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for theme in ('dark', 'light'):
        for category in registry.categories():
            definitions = [d for d in registry.definitions() if d.category == category]
            cols = min(3, len(definitions))
            sheet = QImage(cols * 400, ((len(definitions) + cols - 1) // cols) * 340 + 72,
                           QImage.Format_ARGB32)
            sheet.fill(QColor(color('background', theme)))
            painter = QPainter(sheet)
            painter.setRenderHint(QPainter.Antialiasing)
            font = QFont('Segoe UI'); font.setPixelSize(24); font.setWeight(QFont.DemiBold)
            painter.setFont(font); painter.setPen(QColor(color('foreground', theme)))
            painter.drawText(QRectF(24, 12, sheet.width()-48, 48), Qt.AlignVCenter,
                             f'{category}  /  {theme.title()}')
            for index, definition in enumerate(definitions):
                warnings = []
                handler = qInstallMessageHandler(lambda _t, _c, msg: warnings.append(msg))
                view = QQuickView()
                view.engine().addImportPath(str(ROOT / 'ui' / 'qml'))
                props = copy.deepcopy(definition.defaults)
                if samples:
                    props.update(SAMPLES.get(definition.type, {}))
                widget = DesignerWidget(definition.type, 'sample',
                                        {'x': 16, 'y': 16, 'width': definition.default_width,
                                         'height': definition.default_height}, props)
                body = '\n'.join(generator._widget(widget, 1))
                source = ('import QtQuick 2.15\nimport QtQuick.Controls 2.15\nimport Shadcn 1.0\n'
                          f'Rectangle {{ width: {definition.default_width + 32}; '
                          f'height: {definition.default_height + 32}; color: Theme.background; '
                          f'Component.onCompleted: Theme.mode = "{theme}"\n{body}\n}}')
                component = QQmlComponent(view.engine())
                component.setData(source.encode(), QUrl.fromLocalFile(str(output / 'catalog.qml')))
                obj = component.create() if not component.isError() else None
                errors = [e.toString() for e in component.errors()]
                image = QImage()
                if obj is not None:
                    view.setContent(QUrl(), component, obj)
                    view.show(); QTest.qWait(80)
                    image = view.grabWindow()
                    image.save(str(output / f'{theme}-{definition.type}.png'))
                qInstallMessageHandler(handler)
                view.close(); view.deleteLater(); app.processEvents()
                x, y = (index % cols) * 400, (index // cols) * 340 + 72
                painter.setPen(Qt.NoPen); painter.setBrush(QColor(color('card', theme)))
                painter.drawRoundedRect(QRectF(x+12, y+4, 376, 324), 12, 12)
                font.setPixelSize(14); painter.setFont(font)
                painter.setPen(QColor(color('foreground', theme)))
                painter.drawText(QRectF(x+28, y+16, 340, 24), definition.display_name)
                font.setPixelSize(11); painter.setFont(font)
                painter.setPen(QColor(color('mutedForeground', theme)))
                painter.drawText(QRectF(x+28, y+40, 340, 20),
                                 f'{definition.type} · {definition.default_width} × {definition.default_height}')
                if not image.isNull():
                    scaled = image if image.width() <= 360 and image.height() <= 244 else image.scaled(
                        360, 244, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    painter.drawImage(x + (400-scaled.width())//2, y+72+(244-scaled.height())//2, scaled)
                else:
                    painter.setPen(QColor(color('destructive', theme)))
                    painter.drawText(QRectF(x+28, y+100, 340, 160), Qt.TextWordWrap, '\n'.join(errors))
                relevant_warnings = [warning for warning in warnings
                                     if not any(part in warning for part in IGNORED_WARNING_PARTS)]
                report.append({'theme': theme, 'widget': definition.type, 'errors': errors,
                               'warnings': relevant_warnings, 'rendered': not image.isNull()})
            painter.end()
            sheet.save(str(output / f'{theme}-{category.lower()}.png'))
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    failures = [r for r in report if r['errors'] or r['warnings'] or not r['rendered']]
    print(f'{len(report)} renders, {len(failures)} failed; output: {output}')
    for result in failures:
        detail = repr(result['errors'] or result['warnings']).encode('ascii', 'backslashreplace').decode('ascii')
        print(result['widget'], detail)
    return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp' / 'widget-catalog')
    parser.add_argument('--samples', action='store_true', help='Use illustrative values instead of registry defaults')
    args = parser.parse_args()
    raise SystemExit(capture(args.output.resolve(), samples=args.samples))
