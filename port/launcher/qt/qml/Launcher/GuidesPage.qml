import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import Launcher

Item {
    id: page
    readonly property color accent: Theme.neon
    property real zoom: 0                      // 0 = fit to the window width
    readonly property real fitScale: img.sourceSize.width > 0 ? view.width / img.sourceSize.width : 1
    readonly property real scaleNow: zoom > 0 ? zoom : fitScale
    readonly property int side: 36

    Column {
        id: head
        x: page.side; y: 26; width: parent.width - 2 * page.side; spacing: 12
        Text { text: Theme.tr("guides_title"); color: "#fff"; font.family: Theme.fontDisplay; font.variableAxes: ({ "wght": 800 }); font.pixelSize: 42
               font.weight: Font.ExtraBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 2.1 }
        Text { width: parent.width; text: Theme.tr("guides_intro"); wrapMode: Text.WordWrap; color: Theme.textSoft
               font.family: Theme.fontText; font.pixelSize: 14; lineHeight: 1.35; lineHeightMode: Text.ProportionalHeight }
        Row {
            spacing: 8
            Text { text: Theme.tr("guides_kb"); color: Theme.textDim; font.family: Theme.fontText; font.pixelSize: 13
                   anchors.verticalCenter: parent.verticalCenter }
            Text { text: Theme.tr("guides_kb_open") + " →"; color: page.accent; font.family: Theme.fontText; font.pixelSize: 13; font.weight: Font.Bold
                   anchors.verticalCenter: parent.verticalCenter
                   MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.openReadme() } }
        }
        Flow {
            width: parent.width; spacing: 10
            Repeater {
                model: Backend.guideKinds
                Rectangle {
                    readonly property bool on: Backend.guideKind === modelData.key
                    height: 34; radius: 17; width: kindText.implicitWidth + 28
                    color: on ? Theme.navOn : Theme.chip; border.width: 1; border.color: on ? page.accent : Theme.chipLine
                    Text { id: kindText; anchors.centerIn: parent; text: modelData.label; color: parent.on ? "#fff" : Theme.textChip
                           font.family: Theme.fontText; font.pixelSize: 13; font.weight: Font.DemiBold }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setGuideKind(modelData.key) }
                }
            }
            Text { visible: Backend.guideDetected !== ""; text: Backend.guideDetected; color: Theme.textFaint
                   font.family: Theme.fontText; font.pixelSize: 12; height: 34; verticalAlignment: Text.AlignVCenter }
        }
        Flow {
            width: parent.width; spacing: 10
            GhostButton { compact: true; text: Theme.tr("guides_save"); accent: page.accent; enabled: Backend.guideSource !== ""; onClicked: saveDialog.open() }
            GhostButton { compact: true; text: Theme.tr("guides_copy"); enabled: Backend.guideSource !== ""; onClicked: Backend.copyGuide() }
            GhostButton { compact: true; text: Theme.tr("guides_open"); onClicked: Backend.openGuidesFolder() }
            GhostButton { compact: true; text: Theme.tr("guides_fit"); enabled: Backend.guideSource !== "" && page.zoom > 0; onClicked: page.zoom = 0 }
            GhostButton { compact: true; width: 40; implicitWidth: 40; text: "−"; enabled: Backend.guideSource !== ""; onClicked: page.zoom = Math.max(0.25, page.scaleNow / 1.25) }
            GhostButton { compact: true; width: 40; implicitWidth: 40; text: "+"; enabled: Backend.guideSource !== ""; onClicked: page.zoom = Math.min(3, page.scaleNow * 1.25) }
        }
        Text { visible: Backend.guideMessage !== ""; width: parent.width; text: Backend.guideMessage; color: Theme.textSoft; wrapMode: Text.WordWrap
               font.family: Theme.fontText; font.pixelSize: 13 }
    }

    Rectangle {
        id: frame
        x: page.side; y: head.y + head.height + 14
        width: parent.width - 2 * page.side; height: parent.height - y - 24
        radius: 12; color: "#0b0c0f"; border.width: 1; border.color: Theme.cardLine
        clip: true
        Flickable {
            id: view
            anchors.fill: parent; anchors.margins: 1
            clip: true
            contentWidth: Math.max(width, img.width); contentHeight: Math.max(height, img.height)
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            ScrollBar.horizontal: ScrollBar { }
            Image {
                id: img
                source: Backend.guideSource
                visible: source !== ""
                asynchronous: true; smooth: true; mipmap: true
                width: sourceSize.width * page.scaleNow; height: sourceSize.height * page.scaleNow
                x: Math.max(0, (view.width - width) / 2)
            }
        }
        Text { visible: Backend.guideSource === ""; anchors.centerIn: parent; text: Theme.tr("guides_missing"); color: Theme.textDim
               font.family: Theme.fontText; font.pixelSize: 15 }
    }

    FileDialog {
        id: saveDialog
        title: Theme.tr("guides_save_title")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "png"
        nameFilters: ["PNG (*.png)"]
        onAccepted: Backend.saveGuide(selectedFile.toString())
    }
}
