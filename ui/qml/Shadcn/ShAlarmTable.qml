import QtQuick 2.15

// ShAlarmTable -- the active alarm list (rows: severity dot, message,
// NEW/ACK, timestamp), or with `columns` / `sampleRows` set a table:
//   * a compact title bar clamp(round(0.17 h), 22, 36) tall and a column
//     header row clamp(round(0.13 h), 16, 24) tall (when `columns` is set);
//   * one row per alarm with a cell per column, filled by the column's name
//     (time, tag, description/message, priority/severity -> HIGH/MEDIUM/LOW,
//     status -> ACTIVE/ACKED, value, label);
//   * while no live alarm exists the `sampleRows` ("a|b|c;d|e|f") instead of
//     "No active alarms" (a design preview), sharing the body's height (at
//     most rowHeight each);
//   * HIGH/CRITICAL, MEDIUM, LOW, ACTIVE, ACKED cells as small pills (red,
//     amber, blue; ACTIVE a red outline on a red tint, ACKED a grey outline);
//     a row holding ACTIVE draws its other cells in Theme.destructive;
//   * column widths: each column's widest text + 2 x 8 px, grown in
//     proportion, or (too narrow) the columns within a fair share kept and the
//     wide ones shrunk in proportion. Thin Theme.border lines between columns.
// headerColor ("" = Theme.secondary) colours the title bar (title white or
// near-black by its luminance); showCount shows the count badge.
// native/hmi-ui/src/widgets/w_shalarmtable.c draws the same.
Item {
    id: root
    property var alarms: []
    property int maxVisible: 6
    property string title: "Active Alarms"
    property bool showTimestamp: true
    property real rowHeight: 30
    // CONTRACT 13.3: "history" shows the panel's alarm journal; the desktop
    // preview has no journal and shows the active list either way.
    property string mode: "active"
    property string columns: ""
    property string sampleRows: ""
    property string headerColor: ""
    property bool showCount: true
    signal alarmActivated(var alarm)
    implicitWidth: 350
    implicitHeight: rowHeight * maxVisible + 36

    // -- table view ----------------------------------------------------------------
    function _split(s, sep) {
        if (s === "") return [];
        return s.split(sep).map(function(x) { return x.trim() });
    }
    readonly property var _cols: _split(root.columns, ",").slice(0, 8)
    readonly property var _samples: {
        var out = [];
        var rows = root.sampleRows.split(";");
        for (var i = 0; i < rows.length && out.length < 16; ++i) {
            if (rows[i].trim() === "") continue;
            out.push(rows[i].trim().split("|").slice(0, 8).map(function(x) { return x.trim() }));
        }
        return out;
    }
    readonly property bool _table: _cols.length > 0 || _samples.length > 0
    readonly property int _liveCount: root.alarms ? root.alarms.length : 0
    readonly property bool _sample: _liveCount === 0 && _samples.length > 0
    function _ieq(a, b) { return String(a).toLowerCase() === b }
    function _alarmCell(al, name) {
        var n = String(name).toLowerCase();
        if (n === "time" || n === "timestamp" || n === "date") return al.timestamp || "";
        if (n === "tag" || n === "id") return al.tag || "";
        if (n === "label" || n === "name") return al.label || "";
        if (n === "description" || n === "message" || n === "alarm" || n === "text" || n === "event") return al.message || "Alarm";
        if (n === "priority" || n === "severity" || n === "level")
            return al.severity === "fault" ? "HIGH" : (al.severity === "warning" || al.severity === "caution") ? "MEDIUM" : "LOW";
        if (n === "status" || n === "state" || n === "ack") return al.acknowledged ? "ACKED" : "ACTIVE";
        if (n === "value") return al.value === undefined || al.value === null ? "" : String(al.value);
        return "";
    }
    // [cells] per row
    readonly property var _rows: {
        if (_sample) return _samples;
        if (_cols.length === 0) return [];
        var out = [];
        for (var i = 0; i < Math.min(_liveCount, 16); ++i) {
            var r = [];
            for (var c = 0; c < _cols.length; ++c) r.push(_alarmCell(root.alarms[i], _cols[c]));
            out.push(r);
        }
        return out;
    }
    readonly property int _nCols: Math.max(1, _cols.length > 0 ? _cols.length
        : _samples.reduce(function(m, r) { return Math.max(m, r.length) }, 0))
    function _pill(t) {
        var s = String(t).toUpperCase();
        return s === "HIGH" || s === "CRITICAL" ? "high" : s === "MEDIUM" ? "medium" : s === "LOW" ? "low"
             : s === "ACTIVE" ? "active" : s === "ACKED" ? "acked" : "";
    }
    readonly property real _H: Math.max(1, height)
    readonly property real _W: Math.max(1, width)
    readonly property int _headH: _table ? Math.max(22, Math.min(36, Math.round(_H * 0.17))) : 36
    readonly property int _colH: _cols.length > 0 ? Math.max(16, Math.min(24, Math.round(_H * 0.13))) : 0
    readonly property int _rowH: {
        var rh = root.rowHeight > 0 ? Math.floor(root.rowHeight) : 30;
        var avail = Math.max(1, Math.floor(_H - _headH - _colH));
        if (_samples.length > 0) rh = Math.min(rh, Math.max(14, Math.floor(avail / _samples.length)));
        return rh;
    }
    readonly property int _px: Math.max(9, Math.min(13, Math.round(_rowH * 0.6)))
    readonly property int _hpx: Math.max(9, _px - 1)
    readonly property int _ppx: Math.max(8, _px - 1)
    readonly property int _pillH: Math.max(12, Math.min(22, Math.round(_rowH * 0.64)))
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }
    FontMetrics { id: fmCell; font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._px; font.weight: Theme.fontNormal }
    FontMetrics { id: fmHead; font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._hpx; font.weight: Theme.fontMedium }
    FontMetrics { id: fmPill; font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._ppx; font.weight: Theme.fontSemibold }
    function _pillW(t) { return Math.ceil(fmPill.advanceWidth(t)) + 16 }
    // Column left edges (and the right edge last).
    readonly property var _colX: {
        if (!_table) return [0, _W];
        var nat = [], sum = 0;
        for (var c = 0; c < _nCols; ++c) {
            var m = _cols.length > 0 ? Math.ceil(fmHead.advanceWidth(_cols[c])) : 0;
            for (var r = 0; r < _rows.length; ++r) {
                var s = _rows[r][c] || "";
                m = Math.max(m, _pill(s) !== "" ? _pillW(s) : Math.ceil(fmCell.advanceWidth(s)));
            }
            nat.push(m + 16);
            sum += m + 16;
        }
        var width = [];
        if (sum <= _W) {
            for (c = 0; c < _nCols; ++c) width.push(nat[c] * _W / Math.max(1, sum));
        } else {
            var fixed = [], left = _W;
            for (c = 0; c < _nCols; ++c) { fixed.push(false); width.push(0) }
            for (var pass = 0; pass < 8; ++pass) {
                var flex = 0, flexSum = 0;
                for (c = 0; c < _nCols; ++c) if (!fixed[c]) { ++flex; flexSum += nat[c] }
                if (flex === 0) break;
                var changed = false;
                for (c = 0; c < _nCols; ++c)
                    if (!fixed[c] && nat[c] <= left / flex) { fixed[c] = true; width[c] = nat[c]; left -= nat[c]; changed = true }
                if (!changed) {
                    for (c = 0; c < _nCols; ++c) if (!fixed[c]) width[c] = nat[c] * Math.max(0, left) / flexSum;
                    break;
                }
            }
        }
        var xs = [], x = 0;
        for (c = 0; c < _nCols; ++c) { xs.push(Math.round(x)); x += width[c] }
        xs.push(Math.round(_W));
        return xs;
    }
    readonly property bool _customHead: root.headerColor.charAt(0) === "#"
    readonly property color _headFill: _customHead ? root.headerColor : Theme.secondary
    readonly property color _titleInk: {
        if (!_customHead) return Theme.foreground;
        var c = root._headFill;
        return (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) > 0.55 ? "#0b0f14" : "#ffffff";
    }

    Rectangle {
        id: header
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: root._headH; color: root._headFill; radius: Theme.radiusSm
        Text { anchors.left: parent.left; anchors.leftMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - (root.showCount ? 56 : 16); text: root.title; elide: Text.ElideRight; color: root._titleInk; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
        ShBadge { visible: root.showCount; height: root._headH < 28 ? root._headH - 6 : 20; anchors.right: parent.right; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; text: (root._liveCount === 0 && root._table && root._samples.length > 0 ? root._samples.length : root._liveCount).toString(); variant: "secondary" }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: header.bottom; anchors.bottom: parent.bottom
        color: Theme.background; border.color: Theme.border; border.width: 1
        Text {
            anchors.centerIn: parent; anchors.verticalCenterOffset: root._table ? root._colH / 2 : 0
            visible: root._table ? root._rows.length === 0 : root.alarms.length === 0
            text: "No active alarms"; color: Theme.mutedForeground
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm
        }
        ListView {
            anchors.fill: parent; clip: true; visible: !root._table && root.alarms.length > 0
            model: root._table ? [] : root.alarms; boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width; height: root.rowHeight
                color: modelData.acknowledged ? "transparent" : Theme.accent
                Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.border }
                ShStatDot { id: dot; anchors.left: parent.left; anchors.leftMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; size: 8; state: modelData.severity === "fault" ? "fault" : modelData.severity === "warning" || modelData.severity === "caution" ? "warn" : "ok" }
                Text { anchors.left: dot.right; anchors.leftMargin: Theme.spacing8; anchors.right: stateText.left; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; text: modelData.message || "Alarm"; elide: Text.ElideRight; color: modelData.acknowledged ? Theme.mutedForeground : Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm }
                Text { id: stateText; anchors.right: timestamp.left; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: 28; text: modelData.acknowledged ? "ACK" : "NEW"; color: modelData.acknowledged ? Theme.mutedForeground : Theme.brand; font.family: Theme.fontFamily; font.pixelSize: 10 }
                Text { id: timestamp; anchors.right: parent.right; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: root.showTimestamp ? 64 : 0; visible: root.showTimestamp; text: modelData.timestamp || ""; horizontalAlignment: Text.AlignRight; elide: Text.ElideRight; color: Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: 10 }
                MouseArea { anchors.fill: parent; onClicked: root.alarmActivated(modelData) }
            }
        }

        // The table view.
        Item {
            anchors.fill: parent; clip: true; visible: root._table
            Rectangle {
                visible: root._cols.length > 0
                width: parent.width; height: root._colH; color: Theme.secondary
                Repeater {
                    model: root._cols.length
                    delegate: Item {
                        required property int index
                        Text {
                            x: root._colX[index] + 8
                            y: Math.floor((root._colH - root._lineH(root._hpx)) / 2) + root._asc(root._hpx) - baselineOffset
                            width: Math.max(1, root._colX[index + 1] - root._colX[index] - 16)
                            text: root._cols[index]; color: Theme.mutedForeground
                            font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._hpx; font.weight: Theme.fontMedium
                            fontSizeMode: Text.HorizontalFit; minimumPixelSize: Math.max(8, Math.round(root._hpx * 0.8))
                            elide: Text.ElideRight; maximumLineCount: 1
                        }
                        Rectangle { visible: index > 0; x: root._colX[index]; width: 1; height: root._colH; color: Theme.border }
                    }
                }
                Rectangle { y: root._colH - 1; width: parent.width; height: 1; color: Theme.border }
            }
            Repeater {
                model: Math.min(root._rows.length, Math.floor((root._H - root._headH - root._colH) / Math.max(1, root._rowH)) + 1)
                delegate: Rectangle {
                    id: row
                    required property int index
                    readonly property var cells: root._rows[index]
                    readonly property bool active: cells.some(function(c) { return root._pill(c) === "active" })
                    readonly property color ink: active ? Theme.destructive : Theme.foreground
                    y: root._colH + index * root._rowH
                    width: parent.width; height: root._rowH
                    color: root._sample || (root.alarms[index] && root.alarms[index].acknowledged) ? "transparent"
                         : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 90 / 255)
                    Repeater {
                        model: root._nCols
                        delegate: Item {
                            required property int index
                            readonly property string cellText: row.cells[index] || ""
                            readonly property string pill: root._pill(cellText)
                            readonly property int cx: root._colX[index]
                            readonly property int cw: root._colX[index + 1] - root._colX[index]
                            Text {
                                visible: parent.pill === ""
                                x: parent.cx + 8
                                y: Math.floor((root._rowH - root._lineH(root._px)) / 2) + root._asc(root._px) - baselineOffset
                                width: Math.max(1, parent.cw - 16)
                                text: parent.cellText; color: row.ink
                                font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._px; font.weight: Theme.fontNormal
                                elide: Text.ElideRight; maximumLineCount: 1
                            }
                            Rectangle {
                                readonly property int pw: Math.min(parent.cw - 12, Math.max(root._pillW(parent.cellText), Math.round(parent.cw * 0.62)))
                                visible: parent.pill !== "" && pw >= 8
                                x: parent.cx + 6
                                y: Math.floor((root._rowH - root._pillH) / 2)
                                width: pw; height: root._pillH; radius: 3
                                color: parent.pill === "high" ? Theme.destructive : parent.pill === "medium" ? Theme.warning
                                     : parent.pill === "low" ? Theme.info
                                     : parent.pill === "active" ? Qt.rgba(Theme.destructive.r, Theme.destructive.g, Theme.destructive.b, 56 / 255)
                                     : "transparent"
                                border.width: parent.pill === "active" || parent.pill === "acked" ? 1 : 0
                                border.color: parent.pill === "active" ? Theme.destructive : Theme.mutedForeground
                                Text {
                                    x: 2
                                    y: Math.floor((root._pillH - root._lineH(root._ppx)) / 2) + root._asc(root._ppx) - baselineOffset
                                    width: Math.max(1, parent.width - 4)
                                    horizontalAlignment: Text.AlignHCenter
                                    text: parent.parent.cellText
                                    color: parent.parent.pill === "high" || parent.parent.pill === "low" ? "#ffffff"
                                         : parent.parent.pill === "medium" ? "#1a1203"
                                         : parent.parent.pill === "active" ? Theme.destructive : Theme.mutedForeground
                                    font.family: Theme.fontFamily; font.kerning: false; font.pixelSize: root._ppx; font.weight: Theme.fontSemibold
                                    fontSizeMode: Text.HorizontalFit; minimumPixelSize: Math.max(8, Math.round(root._ppx * 0.8))
                                    elide: Text.ElideRight; maximumLineCount: 1
                                }
                            }
                            Rectangle { visible: index > 0; x: parent.cx; width: 1; height: root._rowH; color: Theme.border }
                        }
                    }
                    Rectangle { y: root._rowH - 1; width: parent.width; height: 1; color: Theme.border }
                    MouseArea {
                        anchors.fill: parent; enabled: !root._sample
                        onClicked: root.alarmActivated(root.alarms[row.index])
                    }
                }
            }
        }
    }
}
