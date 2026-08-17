import random
import sys

from PyQt6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QValueAxis,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget


class BarChartWidget(QWidget):
    def __init__(self, title='', xLabel='', yLabel=''):
        super().__init__()

        self.data = [0]
        self.max_val = 1

        # Create a QBarSet and store a reference to it
        self._bar_set = QBarSet("Data")

        # Create a series and add the bar set
        self._series = QBarSeries()
        self._series.append(self._bar_set)

        # Create the chart
        self._chart = QChart()
        self._chart.setBackgroundBrush(QBrush(QColor("black")))
        self._chart.setPlotAreaBackgroundBrush(QBrush(QColor("black")))
        self._chart.setPlotAreaBackgroundVisible(True)
        self._chart.addSeries(self._series)
        self._chart.setTitle(title)
        self._chart.setTitleBrush(QBrush(QColor("white")))

        # Create x-axis (category axis)
        self._categories = [f"{i + 1}" for i in range(len(self.data))]
        self._axis_x = QBarCategoryAxis()
        self._axis_x.setTitleText(xLabel)
        self._axis_x.setLabelsColor(QColor("white"))
        self._axis_x.setTitleBrush(QBrush(QColor("white")))
        self._axis_x.setGridLineVisible(False)
        self._axis_x.setMinorGridLineVisible(False)
        self._axis_x.append(self._categories)
        self._chart.addAxis(self._axis_x, Qt.AlignmentFlag.AlignBottom)
        self._series.attachAxis(self._axis_x)

        # Create y-axis (value axis)
        self._axis_y = QValueAxis()
        self._axis_y.setRange(0, self.max_val + 2)
        self._axis_y.setTitleText(yLabel)
        self._axis_y.setLabelsColor(QColor("white"))
        self._axis_y.setTitleBrush(QBrush(QColor("white")))
        self._axis_y.setGridLineVisible(False)
        self._axis_y.setMinorGridLineVisible(False)
        self._chart.addAxis(self._axis_y, Qt.AlignmentFlag.AlignLeft)
        self._series.attachAxis(self._axis_y)

        # Create the ChartView
        chart_view = QChartView(self._chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Place the ChartView in the widget’s layout
        layout = QVBoxLayout()
        layout.addWidget(chart_view)
        self.setLayout(layout)

    def update_data(self, new_data):
        # Remove old values from the bar set
        self._bar_set.remove(0, self._bar_set.count())

        # Append new values
        self._bar_set.append(new_data)

        # Update x-axis categories if needed
        # (For simplicity, we assume the number of data points remains the same.
        #  If the length changes, you can re-append self._categories here accordingly.)
        if len(new_data) != len(self._categories):
            self._categories = [f"Item {i + 1}" for i in range(len(new_data))]
            self._axis_x.clear()
            self._axis_x.append(self._categories)

        # Update y-axis range to fit the new data
        if max(self.data) > self.max_val:
            self.max_val = max(self.data)
        self._axis_y.setRange(0, self.max_val + 2)

        # Update self.data to keep track of the latest values
        self.data = new_data
