import numpy as np
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QVBoxLayout, QWidget

class XYZPlotWidget(QWidget):
    def __init__(self):
        super().__init__()

        # Create a layout for the widget
        layout = QVBoxLayout(self)
        self.setLayout(layout)
        
        # Create the GLViewWidget (3D View)
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=10)
        layout.addWidget(self.view)
        
        # Add a grid for better visualization
        grid = gl.GLGridItem()
        grid.scale(1, 1, 1)  # Set grid spacing
        self.view.addItem(grid)
        
        self.x = []
        self.y = []
        self.z = []
        
        # Create a scatter plot item
        self.scatter = gl.GLScatterPlotItem(
            pos=np.column_stack((self.x, self.y, self.z)),
            size=10,
            color=(1, 1, 0, 1),  # Yellow points
            pxMode=True
        )
        self.view.addItem(self.scatter)
            
    def setData(self, data):
        self.x = data[0]
        self.y = data[1]
        self.z = data[2]
                
        self.scatter.setData(pos=np.column_stack((self.x, self.y, self.z)))
                    
