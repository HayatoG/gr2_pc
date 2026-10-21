import QtQuick
import QtQuick.Controls.Basic
import Launcher

ComboBox {
    id: root
    property color accent: Theme.smoke
    implicitWidth: 220
    implicitHeight: 36
    textRole: "label"
    font.family: Theme.fontText
    font.pixelSize: 13
    font.weight: Font.DemiBold
    background: Rectangle {
        radius: 8
        color: root.hovered ? Theme.ghostHover : Theme.ghost
        border.width: 1
        border.color: root.visualFocus || root.popup.visible ? root.accent : Theme.ghostLine
    }
    contentItem: Text {
        leftPadding: 12; rightPadding: 28
        text: root.displayText; color: Theme.text; font: root.font
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Text { text: "▾"; color: Theme.textMuted; x: root.width - width - 10
                      anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12 }
    delegate: ItemDelegate {
        width: root.width
        highlighted: root.highlightedIndex === index
        contentItem: Text { text: modelData.label !== undefined ? modelData.label : modelData
                            color: Theme.text; font: root.font; elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: highlighted ? Theme.navOn : Theme.card }
    }
    popup: Popup {
        y: root.height + 2; width: root.width; padding: 1
        implicitHeight: Math.min(contentItem.implicitHeight + 2, 260)
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: root.popup.visible ? root.delegateModel : null
                                currentIndex: root.highlightedIndex }
        background: Rectangle { color: Theme.card; border.color: Theme.ghostLine; radius: 8 }
    }
}
