import QtQuick
import QtQuick.Controls.Basic
import Launcher

Item {
    id: row
    property var d: ({})
    readonly property color accent: Theme.cyan
    width: ListView.view ? ListView.view.width : 600
    height: card.height + 8

    Rectangle {
        id: card
        y: 4; width: parent.width; radius: 12
        height: Math.max(78, info.implicitHeight + 28)
        color: Theme.card
        border.width: 1; border.color: d.on ? Qt.rgba(row.accent.r, row.accent.g, row.accent.b, 0.7) : Theme.cardLine
        Column {
            id: info
            x: 18; y: 14; width: parent.width - 36 - 80; spacing: 5
            Text { text: d.label || ""; color: Theme.text; font.family: Theme.fontText; font.pixelSize: 15; font.weight: Font.DemiBold }
            Text { width: parent.width; text: d.what || ""; wrapMode: Text.WordWrap; color: Theme.textDim
                   font.family: Theme.fontText; font.pixelSize: 13; lineHeight: 1.3; lineHeightMode: Text.ProportionalHeight
                   visible: !!d.what }
        }
        Toggle {
            anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter
            accent: row.accent
            checked: d.on === true
            onToggled: (v) => Backend.setMod(d.id, v)
        }
    }
}
