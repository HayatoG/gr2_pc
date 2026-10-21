import QtQuick
import Launcher

Rectangle {
    id: root
    property bool checked: false
    property color accent: Theme.smoke
    signal toggled(bool value)
    width: 46; height: 26; radius: 13
    color: checked ? accent : "#262b33"
    border.width: 1
    border.color: checked ? Qt.lighter(accent, 1.2) : "#3a404b"
    Behavior on color { ColorAnimation { duration: 140 } }
    Rectangle {
        y: 3; width: 20; height: 20; radius: 10
        x: root.checked ? parent.width - width - 3 : 3
        color: root.checked ? "#160a04" : "#a3a9b3"
        Behavior on x { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
    }
    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.toggled(!root.checked) }
    Accessible.role: Accessible.CheckBox
    Accessible.checked: checked
}
