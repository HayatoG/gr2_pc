import QtQuick
import Launcher

// Section heading: accent bar + display type.
Row {
    id: root
    property string text: ""
    property color accent: Theme.smoke
    spacing: 10
    Rectangle { width: 4; height: 20; color: root.accent; anchors.verticalCenter: parent.verticalCenter }
    Text { text: root.text; color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 22
           font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 1.3
           anchors.verticalCenter: parent.verticalCenter }
}
