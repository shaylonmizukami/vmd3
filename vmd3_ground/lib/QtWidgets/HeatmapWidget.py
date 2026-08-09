import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

class HeatmapWidget(QWidget):
    def __init__(self, title='', xLabel='', yLabel='', xUnit='', yUnit='', xTickLimits=[0, 1], yTickLimits=[0, 1]):
        super().__init__()
        self.xTickLimits = xTickLimits
        self.yTickLimits = yTickLimits

        # Create a layout for the widget
        layout = QVBoxLayout(self)

        # Create a PyQtGraph PlotWidget
        self.plot_widget = pg.PlotWidget()
        layout.addWidget(self.plot_widget)

        # Generate example data for the heatmap (2D array)
        self.data = np.zeros((100, 100))  # 100x100 random data as an example

        # Create the ImageItem for displaying the heatmap
        self.heatmap = pg.ImageItem(self.data)

        # Add the heatmap to the plot
        self.plot_widget.addItem(self.heatmap)

        # Set up color map for better visualization
        self.color_map = pg.colormap.get("inferno")
        self.heatmap.setLookupTable(self.color_map.getLookupTable())

        # Set axis labels
        self.plot_widget.setTitle(title, color='w', size='16', bold=True)
        self.plot_widget.setLabel('left', yLabel, units=yUnit)
        self.plot_widget.setLabel('bottom', xLabel, units=xUnit)
                
        self.plot_widget.scene().sigMouseMoved.connect(self.show_coordinates)
        self.coord_label = pg.TextItem("", anchor=(0, 0), color="w")
        self.plot_widget.addItem(self.coord_label)
        
    def setData(self, data):
        self.heatmap.setImage(data)
                                
        self.yAxis = np.linspace(self.yTickLimits[0], self.yTickLimits[1], len(data[0]))
        self.xAxis = np.linspace(self.xTickLimits[0], self.xTickLimits[1], len(data))
                
        # y_ticks = [(int(i), f'{self.yAxis[i]:.1f}') for i in range(0, len(self.yAxis), int(len(self.yAxis) / 10))]
        # self.plot_widget.getAxis('left').setTicks([y_ticks])
                
        # x_ticks = [(int(i), f'{self.xAxis[i]:.1f}') for i in range(0, len(self.xAxis), int(len(self.xAxis) / 10))]
        # self.plot_widget.getAxis('bottom').setTicks([x_ticks])
        
        self.heatmap.setRect(
            min(self.xAxis), min(self.yAxis),
            max(self.xAxis) - min(self.xAxis),
            max(self.yAxis) - min(self.yAxis)
        )
        
    def show_coordinates(self, position):
        """Display the data coordinates when the mouse hovers over the plot."""
        # Map the mouse position from scene to data coordinates
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(position)
        x, y = mouse_point.x(), mouse_point.y()

        # Check if the coordinates are within the data range
        x_min, x_max = min(self.xAxis), max(self.xAxis)
        y_min, y_max = min(self.yAxis), max(self.yAxis)

        if x_min <= x <= x_max and y_min <= y <= y_max:
            # Convert plot coordinates to heatmap indices
            row = int((y - y_min) / (y_max - y_min) * (self.heatmap.image.shape[0] - 1))
            col = int((x - x_min) / (x_max - x_min) * (self.heatmap.image.shape[1] - 1))
            
            # Get heatmap value and print
            value = self.heatmap.image[row, col]
            
            # Update text item position and content
            self.coord_label.setText(f'      ({x:.2f}, {y:.2f})')
            self.coord_label.setPos(x, y)
        else:
            # Hide the label if the mouse is out of bounds
            self.coord_label.setText("")
