import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string path: ""
    property color color: "white"
    property real size: 20
    implicitWidth: size
    implicitHeight: size
    Shape {
        width: 24; height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        ShapePath {
            strokeColor: root.color
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.path }
        }
    }
}
