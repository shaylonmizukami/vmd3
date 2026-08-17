from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget


class QDropdown(QWidget):
    def __init__(self, label='', defaultIndex=0, onChange=None):
        super().__init__()

        self.defaultIndex = defaultIndex
        self.layout = QHBoxLayout(self)

        self.label = QLabel(label)
        self.label.setFixedWidth(100)

        self.combobox = QComboBox()
        self.combobox.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.combobox.setMaxVisibleItems(10)
        self.combobox.currentIndexChanged.connect(onChange)
        print(defaultIndex)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.combobox)

    def addItem(self, item):
        self.combobox.addItem(item)
        self.combobox.setCurrentIndex(self.defaultIndex)
