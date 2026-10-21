import QtQuick
import Launcher

Rectangle {
    id: root
    property string text: ""
    property string level: "ok"   // ok | warn | bad | off
    implicitHeight: 34
    implicitWidth: row.implicitWidth + 24
    radius: 17
    color: Theme.chip
    border.width: 1
    border.color: Theme.chipLine
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Rectangle {
            width: 8; height: 8; radius: 4
            anchors.verticalCenter: parent.verticalCenter
            color: root.level === "ok" ? Theme.ok : root.level === "warn" ? Theme.warn
                 : root.level === "bad" ? Theme.bad : Theme.off
        }
        Text { text: root.text; color: Theme.textChip; font.family: Theme.fontText
               font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
    }
}
