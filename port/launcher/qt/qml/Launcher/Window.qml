import QtQuick
import QtQuick.Window
import Launcher

Window {
    id: win
    property alias current: main.current
    property alias animate: main.animate
    width: 1120
    height: 756  // one more rail entry than inFAMOUS's Window.qml (Mods/Cheats)
    minimumWidth: 1000
    minimumHeight: 600
    visible: true
    color: Theme.bg
    title: "Gravity Rush 2 — PC"
    Main { id: main; anchors.fill: parent }
}
