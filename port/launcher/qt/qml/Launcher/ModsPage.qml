import QtQuick
import QtQuick.Controls.Basic
import Launcher

Item {
    id: page
    readonly property color accent: Theme.cyan

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 36; anchors.rightMargin: 36
        clip: true
        model: Backend.modsModel
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        delegate: ModRow { d: model.d }
        footer: Item { width: 1; height: 24 }
        header: Column {
            width: list.width; spacing: 10
            topPadding: 26; bottomPadding: 8
            Text { text: Theme.tr("mods_title"); color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 42
                   font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 2.1 }
            Text { width: parent.width; text: Theme.tr("mods_intro"); wrapMode: Text.WordWrap; color: Theme.textDim
                   font.family: Theme.fontText; font.pixelSize: 13; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }
            Row {
                spacing: 10
                GhostButton { compact: true; text: Theme.tr("mods_folder"); onClicked: Backend.openModsFolder() }
                GhostButton { compact: true; text: Theme.tr("mods_refresh"); onClicked: Backend.refreshMods() }
            }
            Item {
                width: parent.width; height: warn.implicitHeight
                visible: list.count === 0
                Rectangle { width: 3; height: parent.height; color: Theme.warn }
                Text { id: warn; x: 15; width: parent.width - 15; text: Theme.tr("mods_empty"); wrapMode: Text.WordWrap
                       color: Theme.textDim; font.family: Theme.fontText; font.pixelSize: 12; lineHeight: 1.35
                       lineHeightMode: Text.ProportionalHeight }
            }
        }
        ScrollBar.vertical: ScrollBar {
            id: bar
            contentItem: Rectangle { implicitWidth: 6; radius: 3; color: bar.pressed ? Theme.ghostLineHover : Theme.ghostLine }
            background: Item { }
        }
    }
}
