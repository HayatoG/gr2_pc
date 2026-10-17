import QtQuick
import QtQuick.Controls.Basic
import Launcher

Item {
    id: page
    readonly property color accent: Theme.warn
    readonly property int side: 36

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width; contentHeight: body.implicitHeight + 60
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            id: bar
            contentItem: Rectangle { implicitWidth: 6; radius: 3; color: bar.pressed ? Theme.ghostLineHover : Theme.ghostLine }
            background: Item { }
        }

        Column {
            id: body
            x: page.side; y: 26; width: flick.width - 2 * page.side; spacing: 14

            Text { text: Theme.tr("upd_title"); color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 42
                   font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 2.1 }
            Text { width: parent.width; text: Theme.tr("upd_intro"); wrapMode: Text.WordWrap; color: Theme.textDim
                   font.family: Theme.fontText; font.pixelSize: 13; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }

            Rectangle {
                width: parent.width; height: versions.implicitHeight + 40
                radius: 14; color: Theme.card; border.width: 1
                border.color: Updates.available ? Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.7) : Theme.cardLine
                Rectangle { visible: Updates.available; width: 3; height: parent.height - 2; x: 1; y: 1; color: Theme.warn }
                Column {
                    id: versions
                    x: 22; y: 20; width: parent.width - 44; spacing: 14
                    Row {
                        spacing: 48
                        Column {
                            spacing: 4
                            Text { text: Theme.tr("upd_current"); color: Theme.textMuted; font.family: Theme.fontText; font.pixelSize: 12
                                   font.weight: Font.Bold; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
                            Text { text: Updates.current; color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 30
                                   font.weight: Font.ExtraBold; font.letterSpacing: 1 }
                        }
                        Column {
                            spacing: 4
                            Text { text: Theme.tr("upd_latest"); color: Theme.textMuted; font.family: Theme.fontText; font.pixelSize: 12
                                   font.weight: Font.Bold; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
                            Text { text: Updates.latest + (Updates.published !== "" ? "  ·  " + Updates.published : ""); color: Updates.available ? Theme.warn : "#fff"
                                   font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 30
                                   font.weight: Font.ExtraBold; font.letterSpacing: 1 }
                        }
                    }
                    Row {
                        spacing: 10
                        Rectangle { width: 4; height: statusText.implicitHeight; color: Updates.tone === "bad" ? Theme.bad : Updates.tone === "warn" ? Theme.warn
                                                                                  : Updates.tone === "good" ? Theme.ok : Theme.textMuted }
                        Text { id: statusText; width: versions.width - 14; text: Updates.statusText; wrapMode: Text.WordWrap; color: Theme.text
                               font.family: Theme.fontText; font.pixelSize: 15; font.weight: Font.DemiBold }
                    }
                    Row {
                        spacing: 10
                        GhostButton { tone: "primary"; accent: Theme.warn; text: Theme.tr("upd_check"); enabled: !Updates.checking; onClicked: Updates.check() }
                        GhostButton { text: Theme.tr("upd_download"); enabled: Updates.canDownload; onClicked: Updates.download() }
                    }
                }
            }

            Rectangle {
                width: parent.width; height: optionRow.implicitHeight + 36
                radius: 12; color: Theme.card; border.width: 1; border.color: Theme.cardLine
                Row {
                    id: optionRow
                    x: 20; y: 18; width: parent.width - 40; spacing: 16
                    Toggle { id: sw; accent: page.accent; checked: Updates.checkOnOpen; onToggled: (v) => Updates.setCheckOnOpen(v)
                             anchors.verticalCenter: parent.verticalCenter }
                    Column {
                        width: parent.width - sw.width - 16; spacing: 3
                        anchors.verticalCenter: parent.verticalCenter
                        Text { text: Theme.tr("upd_check_on_open"); color: "#fff"; font.family: Theme.fontText; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Text { width: parent.width; text: Theme.tr("upd_check_on_open_note"); wrapMode: Text.WordWrap; color: Theme.textDim
                               font.family: Theme.fontText; font.pixelSize: 12 }
                    }
                }
            }

            Row {
                visible: Updates.notes !== ""
                spacing: 10
                Rectangle { width: 4; height: 20; color: page.accent; anchors.verticalCenter: parent.verticalCenter }
                Text { text: Theme.tr("upd_notes"); color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 22
                       font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 1.3
                       anchors.verticalCenter: parent.verticalCenter }
            }
            Rectangle {
                visible: Updates.notes !== ""
                width: parent.width; height: notesText.implicitHeight + 36
                radius: 12; color: Theme.card; border.width: 1; border.color: Theme.cardLine
                TextEdit { id: notesText; x: 20; y: 18; width: parent.width - 40; text: Updates.notes; readOnly: true; selectByMouse: true
                           wrapMode: TextEdit.Wrap; color: Theme.textSoft; selectionColor: page.accent; selectedTextColor: "#171100"
                           font.family: Theme.fontText; font.pixelSize: 14 }
            }
            Item { width: 1; height: 30 }
        }
    }
}
