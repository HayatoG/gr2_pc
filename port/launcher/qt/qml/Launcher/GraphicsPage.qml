import QtQuick
import QtQuick.Controls.Basic
import Launcher

Item {
    id: page
    readonly property color accent: Theme.video
    readonly property int side: 36

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width; contentHeight: body.implicitHeight + 60
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Connections { target: Graphics; function onScrollRequested(y) { flick.contentY = Math.max(0, Math.min(y, flick.contentHeight - flick.height)) } }
        ScrollBar.vertical: ScrollBar {
            id: bar
            contentItem: Rectangle { implicitWidth: 6; radius: 3; color: bar.pressed ? Theme.ghostLineHover : Theme.ghostLine }
            background: Item { }
        }

        Column {
            id: body
            x: page.side; y: 26; width: flick.width - 2 * page.side; spacing: 14

            Text { text: Theme.tr("gfx_title"); color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 42
                   font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 2.1 }
            Text { width: parent.width; text: Theme.tr("gfx_intro"); wrapMode: Text.WordWrap; color: Theme.textDim
                   font.family: Theme.fontText; font.pixelSize: 13; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }

            // ---- presets ----------------------------------------------------------------------
            Row {
                spacing: 14
                SectionTitle { text: Theme.tr("gfx_presets_title"); accent: page.accent; anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: now.implicitWidth + 24; height: 30; radius: 15
                    color: Theme.chip; border.width: 1; border.color: Graphics.presets.some(function (p) { return p.active }) ? page.accent : Theme.warn
                    Text { id: now; anchors.centerIn: parent; text: Graphics.presetText; color: Theme.textChip
                           font.family: Theme.fontText; font.pixelSize: 13; font.weight: Font.Bold }
                }
            }
            Row {
                id: presetRow
                width: parent.width; spacing: 12
                Repeater {
                    model: Graphics.presets
                    Rectangle {
                        readonly property bool hot: presetMouse.containsMouse
                        width: (presetRow.width - 3 * presetRow.spacing) / 4; height: 150; radius: 12
                        color: modelData.active ? Qt.rgba(page.accent.r, page.accent.g, page.accent.b, 0.10) : hot ? Theme.navHover : Theme.card
                        border.width: modelData.active ? 2 : 1
                        border.color: modelData.active ? page.accent : hot ? Theme.ghostLineHover : Theme.cardLine
                        Column {
                            x: 14; y: 13; width: parent.width - 28; spacing: 7
                            Row {
                                spacing: 8
                                Text { text: modelData.label; color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 20
                                       font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 0.8
                                       anchors.verticalCenter: parent.verticalCenter }
                                Tag { visible: modelData.standard; text: Theme.tr("gfx_preset_standard"); tone: "good"; anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text { width: parent.width; text: modelData.what; wrapMode: Text.WordWrap; color: Theme.textDim
                                   font.family: Theme.fontText; font.pixelSize: 12; lineHeight: 1.3; lineHeightMode: Text.ProportionalHeight }
                        }
                        MouseArea { id: presetMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: Graphics.applyPreset(modelData.id) }
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.label
                    }
                }
            }
            NoteBar { text: Theme.tr("gfx_preset_note"); bar: page.accent }

            // ---- the options ------------------------------------------------------------------
            Column {
                width: parent.width; spacing: 2
                Repeater {
                    model: Graphics.rows
                    OptionRow {
                        d: model.d; accent: page.accent
                        onValueSet: (id, value) => Graphics.setValue(id, value)
                        onActionTriggered: (id, action) => Graphics.runAction(id, action)
                    }
                }
            }

            // ---- shader cache ------------------------------------------------------------------
            SectionTitle { text: Theme.tr("gfx_sec_cache"); accent: page.accent }
            Rectangle {
                width: parent.width; height: cacheCol.implicitHeight + 36
                radius: 14; color: Theme.card; border.width: 1; border.color: Theme.cardLine
                Column {
                    id: cacheCol
                    x: 18; y: 18; width: parent.width - 36; spacing: 10
                    Text { text: Graphics.cacheText; color: "#fff"; font.family: Theme.fontText; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Text { width: parent.width; text: Theme.tr("gfx_cache_hint"); wrapMode: Text.WordWrap; color: Theme.textDim
                           font.family: Theme.fontText; font.pixelSize: 13; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }
                    NoteBar { visible: Graphics.gameRunning; text: Theme.tr("gfx_cache_running"); bar: Theme.bad }
                    NoteBar { visible: Graphics.message !== ""; text: Graphics.message
                              bar: Graphics.messageTone === "good" ? Theme.ok : Theme.bad; textColor: Theme.textSoft }
                    Text { visible: Graphics.confirming; width: parent.width; text: Graphics.confirmText; wrapMode: Text.WordWrap; color: Theme.textSoft
                           font.family: Theme.fontText; font.pixelSize: 14; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }
                    Row {
                        spacing: 10
                        GhostButton { visible: !Graphics.confirming; compact: true; text: Theme.tr("clear_cache"); enabled: Graphics.canClear
                                      onClicked: Graphics.askClear() }
                        GhostButton { visible: Graphics.confirming; compact: true; tone: "danger"; text: Theme.tr("gfx_cache_yes"); onClicked: Graphics.clearCache() }
                        GhostButton { visible: Graphics.confirming; compact: true; text: Theme.tr("gfx_cache_no"); onClicked: Graphics.cancelClear() }
                    }
                }
            }
        }
    }
}
