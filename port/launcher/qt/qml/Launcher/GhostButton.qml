import QtQuick
import Launcher

Rectangle {
    id: root
    property string text: ""
    property bool compact: false
    property string tone: "ghost"          // ghost | primary (accent fill) | danger
    property color accent: Theme.ok
    signal clicked()
    readonly property color toneColor: tone === "danger" ? Theme.bad : accent
    implicitHeight: compact ? 36 : 44
    implicitWidth: label.implicitWidth + 36
    radius: 10
    opacity: enabled ? 1 : 0.38
    color: tone === "primary" ? (mouse.containsMouse ? Qt.lighter(accent, 1.1) : accent)
         : tone === "danger" ? (mouse.containsMouse ? Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.22) : Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.10))
         : (mouse.containsMouse ? Theme.ghostHover : Theme.ghost)
    border.width: 1
    border.color: tone === "primary" ? accent
                : tone === "danger" ? Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.6)
                : (mouse.containsMouse ? Theme.ghostLineHover : Theme.ghostLine)
    Text { id: label; anchors.centerIn: parent; text: root.text
           color: root.tone === "primary" ? "#06140c" : root.tone === "danger" ? root.toneColor : Theme.text
           font.family: Theme.fontText; font.pixelSize: 14; font.weight: Font.DemiBold
           elide: Text.ElideRight; width: Math.min(implicitWidth, parent.width - 16); horizontalAlignment: Text.AlignHCenter }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: root.clicked() }
    Accessible.role: Accessible.Button
    Accessible.name: text
}
