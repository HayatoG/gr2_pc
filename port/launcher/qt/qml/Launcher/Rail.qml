import QtQuick
import Launcher

Rectangle {
    id: root
    property int current: 0
    onCurrentChanged: navFlick.reveal()
    signal pick(int index)
    color: Theme.rail
    width: Theme.railWidth
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.railLine }

    readonly property var entries: [
        { key: "play", label: "nav_play" }, { key: "graphics", label: "nav_graphics" },
        { key: "controls", label: "nav_controls" }, { key: "fixes", label: "nav_fixes" },
        { key: "mods", label: "nav_mods" },
        { key: "saves", label: "nav_saves" }, { key: "guides", label: "nav_guides" },
        { key: "support", label: "nav_support" }, { key: "updates", label: "nav_updates" },
        { key: "advanced", label: "nav_advanced" } ]

    // The menu scrolls when the window is too short for every entry: it never runs under the
    // language/credits block at the bottom (down to the 600 px minimum height).
    // The title stays fixed (unclipped, it may run past the rail's edge as before).
    Item {
        id: brand
        x: 16; y: 22; width: parent.width - 33; height: 76
        Column {
            x: 6; y: 2; spacing: 2
            Text { text: "Gravity Rush 2"; color: "#ffffff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 34
                   font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase
                   font.letterSpacing: 1.7; lineHeight: 0.95 }
            Text { text: "PC"; color: Theme.smoke; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 700 }); font.pixelSize: 15
                   font.weight: Font.Bold; font.capitalization: Font.AllUppercase; font.letterSpacing: 4.8 }
        }
    }
    Flickable {
        id: navFlick
        anchors.top: brand.bottom; anchors.topMargin: 6; anchors.bottom: footer.top; anchors.bottomMargin: 10
        x: 16; width: parent.width - 33
        contentHeight: navCol.height; contentWidth: width
        clip: true; boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        function reveal() {   // keeps the current entry in view (keyboard/page jumps, short windows)
            var item = navRepeater.itemAt(root.current)
            if (!item) return
            if (item.y < contentY) contentY = item.y
            else if (item.y + item.height > contentY + height) contentY = item.y + item.height - height
        }
        onHeightChanged: reveal()
    Column {
        id: navCol
        width: parent.width; spacing: 6
        Repeater {
            id: navRepeater
            model: root.entries
            NavButton {
                width: parent.width
                label: Theme.tr(modelData.label)
                iconPath: Theme.icons[modelData.key]
                accent: Theme.accents[modelData.key]
                current: root.current === index
                badge: modelData.key === "updates" && Updates.available
                onClicked: root.pick(index)
            }
        }
    }
    }
    Rectangle {   // hint that the menu continues below
        visible: navFlick.interactive && !navFlick.atYEnd
        anchors.bottom: navFlick.bottom; x: 16; width: navFlick.width; height: 18
        gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Theme.rail } }
    }

    Column {
        id: footer
        anchors.bottom: parent.bottom; anchors.bottomMargin: 22
        x: 22; width: parent.width - 44; spacing: 12
        Row {
            spacing: 6; width: parent.width
            Repeater {
                model: [ { code: "pt_BR", label: "PT-BR" }, { code: "en_US", label: "EN-US" } ]
                Rectangle {
                    readonly property bool on: Backend.lang === modelData.code
                    width: (parent.width - 6) / 2; height: 34; radius: 8
                    color: on ? Theme.navOn : "transparent"
                    border.width: 1; border.color: on ? Theme.smoke : Theme.chipLine
                    Text { anchors.centerIn: parent; text: modelData.label; color: parent.on ? "#fff" : Theme.textMuted
                           font.family: Theme.fontText; font.pixelSize: 13; font.weight: Font.Bold }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setLang(modelData.code) }
                }
            }
        }
        Text {
            text: (Backend.version ? Backend.version + " · " : "") + Theme.tr("footer_credit") + "\n" + Theme.tr("footer_license")
            color: Theme.textFaint; font.family: Theme.fontText; font.pixelSize: 12; lineHeight: 1.25
        }
    }
}
