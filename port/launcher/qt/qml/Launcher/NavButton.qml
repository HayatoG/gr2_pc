import QtQuick
import Launcher

Rectangle {
    id: root
    property string label: ""
    property string iconPath: ""
    property color accent: Theme.smoke
    property bool current: false
    property bool badge: false
    signal clicked()
    height: 46
    radius: 10
    color: current ? Theme.navOn : (mouse.containsMouse ? Theme.navHover : "transparent")
    border.width: 1
    border.color: current ? Theme.navOnLine : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }
    Rectangle {   // the accent bar of the current section (inset 3px shadow in the mock)
        visible: root.current
        x: 1; y: 1; width: 3; height: parent.height - 2
        radius: 1
        color: root.accent
    }
    Row {
        anchors.verticalCenter: parent.verticalCenter
        x: 14
        spacing: 12
        Icon { path: root.iconPath; color: root.current || mouse.containsMouse ? "#ffffff" : Theme.textMuted; size: 20
               anchors.verticalCenter: parent.verticalCenter }
        Text {
            text: root.label
            color: root.current || mouse.containsMouse ? "#ffffff" : Theme.textMuted
            font.family: Theme.fontText; font.pixelSize: 15; font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    Rectangle {
        visible: root.badge
        width: 8; height: 8; radius: 4; color: Theme.warn
        anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: root.clicked() }
    Accessible.role: Accessible.Button
    Accessible.name: label
}
