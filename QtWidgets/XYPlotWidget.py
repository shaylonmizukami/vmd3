import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

class XYPlotWidget(QWidget):
    def __init__(self, title='', xLabel='', yLabel='', xUnit='', yUnit=''):
        super().__init__()

        # Create a layout for the widget
        layout = QVBoxLayout(self)
        
        # Create a PlotWidget from PyQtGraph
        self.plot_widget = pg.PlotWidget()
        layout.addWidget(self.plot_widget)
        
        # Set axis labels
        self.plot_widget.setTitle(title, color="w", size="16", bold=True)
        self.plot_widget.setLabel("left", yLabel, units=yUnit)
        self.plot_widget.setLabel("bottom", xLabel, units=xUnit)
        
        self.curve = self.plot_widget.plot(
            [], [], name="Real-Time Data", pen=pg.mkPen(color="w", width=2)
        )
        
        # Store data for updating
        self.x_data = []
        self.y_data = []
        
        self.plot_widget.scene().sigMouseMoved.connect(self.show_coordinates)
        self.coord_label = pg.TextItem("", anchor=(0, 0), color="w")
        self.plot_widget.addItem(self.coord_label)
        
    def update_plot(self, x, y):
        """Update the plot with new data."""
        self.x_data.append(x)
        self.y_data.append(y)
        self.curve.setData(self.x_data, self.y_data)  # Update the graph
        
    def set_plot(self, x, y):
        """Overwrite the plot with new data."""
        self.x_data = x
        self.y_data = y
        self.curve.setData(self.x_data, self.y_data)
        
    def show_coordinates(self, position):
        if self.plot_widget.sceneBoundingRect().contains(position):
            # Map scene position to plot coordinates
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(position)
            x, y = mouse_point.x(), mouse_point.y()
            self.coord_label.setText(f'      ({x:.2f}, {y:.2f})')
            self.coord_label.setPos(x, y)
        else:
            # Hide the label if the mouse is out of bounds
            self.coord_label.setText("")
