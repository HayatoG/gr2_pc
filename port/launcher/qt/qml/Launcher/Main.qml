import QtQuick
import QtQuick.Controls.Basic
import Launcher

Rectangle {
    id: root
    color: Theme.bg
    implicitWidth: 1120
    implicitHeight: 756  // one more rail entry than inFAMOUS's Main.qml (Mods/Cheats): +56px so it fits above the language toggle
    property int current: 0
    readonly property var pages: ["play", "graphics", "controls", "fixes", "mods", "saves", "guides", "support", "updates", "advanced"]
    property bool animate: true

    Rail {
        id: rail
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        current: root.current
        onPick: (i) => root.current = i
    }
    Item {
        id: stage
        anchors.left: rail.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        clip: true
        Repeater {
            model: root.pages.length
            Item {
                id: slot
                readonly property bool on: root.current === index
                width: stage.width; height: stage.height
                opacity: on ? 1 : 0
                visible: opacity > 0.01
                y: on ? 0 : 14
                Behavior on opacity { enabled: root.animate; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Behavior on y { enabled: root.animate; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                Loader {
                    anchors.fill: parent
                    sourceComponent: { var k = root.pages[index]
                        return k === "play" ? home : k === "graphics" ? graphics : k === "controls" ? controls
                             : k === "fixes" ? fixes : k === "mods" ? mods : k === "saves" ? saves
                             // Controller guide artwork is not drawn for this game yet (follow-up): Guides
                             // falls back to the "coming soon" placeholder instead of an empty GuidesPage.
                             : k === "support" ? support : k === "updates" ? updates : k === "advanced" ? advanced : soon }
                    onLoaded: if (item.key !== undefined) item.key = root.pages[index]
                }
            }
        }
    }
    Component { id: home; HomePage { animate: root.animate; onOpenFixes: root.current = 3; onOpenSaves: root.current = 4 } }
    Component { id: graphics; GraphicsPage { } }
    Component { id: controls
        ControlsPage { guidesShown: root.pages.indexOf("guides") >= 0
                       onOpenGuides: root.current = root.pages.indexOf("guides") } }
    Component { id: fixes; FixesPage { } }
    Component { id: mods; ModsPage { } }
    Component { id: advanced; AdvancedPage { } }
    Component { id: saves; SavesPage { } }
    Component { id: support; SupportPage { } }
    Component { id: updates; UpdatesPage { } }
    Component { id: soon; SoonPage { } }
}
