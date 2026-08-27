# -*- coding: utf-8 -*-
"""
界面层 / The Qt layer.

**这个文件不许 import 任何窗口模块。** 包的 ``__init__`` 一做急切导入，
``import ui.theme`` 就会顺带把整套窗口和 QtWidgets 拉起来，测试里想单独测配色
都得先有一个 QApplication。要哪个模块就显式 ``from ui import xxx``。
"""
