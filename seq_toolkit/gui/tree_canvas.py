"""Canvas 树形预览控件：拓扑布局 + 缩放 + 平移 + 适应窗口。

性能约束：节点数 = 2×物种数−1，几千个物种时逐个建 Canvas item 会卡死界面。
因此绘制前先按视口裁剪，只画落在可视区域内的连线与标签；标签在缩放比例过小时
整体跳过（那时文字本来也糊成一团）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..phylo import LayoutNode, count_nodes, layout_cladogram, parse_newick

MIN_LABEL_SCALE = 0.35      # 小于这个缩放比例就不画叶标签
ZOOM_STEP = 1.2
# 画布尚未被映射（例如所在标签页没被选中）时的兜底视口。
# **Tk 在控件未映射时 winfo_width() 返回的是 1 而不是 0**，所以旧的 `winfo_width() or 400`
# 拿不到兜底、等于按 1 px 宽的视口自适应，整棵树被压成 0.02 倍。
FALLBACK_WIDTH = 400
FALLBACK_HEIGHT = 300


class TreeCanvas(ttk.Frame):
    """带工具栏的树预览控件。``set_tree(None)`` 清空。"""

    def __init__(self, parent, *, leaf_gap: float = 18.0,
                 level_gap: float = 180.0) -> None:
        super().__init__(parent)
        self._leaf_gap = leaf_gap
        self._level_gap = level_gap
        self._layout: LayoutNode | None = None
        self._scale = 1.0
        self._offset = [20.0, 20.0]
        self._drag: tuple[float, float] | None = None
        # 上一次 fit() 是否按兜底尺寸算的。为 True 时，画布第一次拿到真实尺寸要补算一次。
        self._fitted_with_fallback = False

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="放大", command=lambda: self.zoom(ZOOM_STEP)).pack(side="left")
        ttk.Button(bar, text="缩小",
                   command=lambda: self.zoom(1 / ZOOM_STEP)).pack(side="left", padx=4)
        ttk.Button(bar, text="适应窗口", command=self.fit).pack(side="left")

        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_drag", None))
        self.canvas.bind("<Configure>", self._on_configure)

    # ---------- 对外接口 ----------

    def set_tree(self, root) -> None:
        self._layout = layout_cladogram(root, leaf_gap=self._leaf_gap,
                                        level_gap=self._level_gap) if root else None
        self.fit()

    def item_count(self) -> int:
        return len(self.canvas.find_all())

    def zoom(self, factor: float) -> None:
        self._scale = max(0.02, min(20.0, self._scale * factor))
        self._draw()

    def fit(self) -> None:
        """缩放到整棵树都在视口内（留 8% 边距）。"""
        self.canvas.update_idletasks()
        width, height = self._viewport()
        # 记录本次是按真实尺寸还是兜底尺寸算的：见 _on_configure。
        self._fitted_with_fallback = not self._is_laid_out()
        if self._layout is None:
            self._draw()
            return
        _total, leaves = count_nodes(self._layout)
        tree_width = self._level_gap * max(1, self._depth(self._layout))
        tree_height = max(1.0, (leaves - 1) * self._leaf_gap)
        self._scale = min(width * 0.92 / max(tree_width, 1.0),
                          height * 0.92 / max(tree_height, 1.0))
        self._scale = max(0.02, min(20.0, self._scale))
        self._offset = [width * 0.04, height * 0.04]
        self._draw()

    # ---------- 内部 ----------

    def _is_laid_out(self) -> bool:
        """画布是否已经拿到真实尺寸（未映射时 Tk 给的是 1）。"""
        return self.canvas.winfo_width() > 1 and self.canvas.winfo_height() > 1

    def _viewport(self) -> tuple[int, int]:
        """当前视口的宽高；未布局时用兜底值。

        兜底必须显式判 ``<= 1``：**Tk 未映射时返回 1，不是 0**，``or 400`` 对 1 不生效。
        """
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        return (width if width > 1 else FALLBACK_WIDTH,
                height if height > 1 else FALLBACK_HEIGHT)

    def _on_configure(self, event) -> None:
        """画布尺寸变化。

        若上一次 ``fit()`` 是按兜底尺寸算的（树是在**隐藏页**里 set_tree 的：建树要
        十几秒到数分钟，用户早切去别的页了），这里必须补算一次——只重画不重算的话，
        scale 会永远停在那次 1 px 视口算出的小值上，用户切回本页看到的就是空画布，
        必须手点「适应窗口」才恢复。
        """
        if (self._layout is not None and self._fitted_with_fallback
                and event.width > 1 and event.height > 1):
            self.fit()
            return
        self._draw()

    @staticmethod
    def _depth(node: LayoutNode) -> int:
        return 1 + max((TreeCanvas._depth(child) for child in node.children),
                       default=0)

    def _to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self._offset[0] + x * self._scale,
                self._offset[1] + y * self._scale)

    def _draw(self) -> None:
        self.canvas.delete("all")
        if self._layout is None:
            return
        width, height = self._viewport()
        draw_labels = self._scale >= MIN_LABEL_SCALE
        stack = [self._layout]
        while stack:
            node = stack.pop()
            stack.extend(node.children)
            px, py = self._to_screen(node.x, node.y)
            for child in node.children:
                cx, cy = self._to_screen(child.x, child.y)
                # 视口裁剪：整条折线都跑到视口外就跳过，不为它建 item
                if (max(py, cy) < -20 or min(py, cy) > height + 20
                        or max(px, cx) < -20 or min(px, cx) > width + 20):
                    continue
                self.canvas.create_line(px, py, cx, py, fill="#4a6fa5")
                self.canvas.create_line(cx, py, cx, cy, fill="#4a6fa5")
            if draw_labels and node.label and not node.children:
                if -40 <= px <= width + 40 and -20 <= py <= height + 20:
                    self.canvas.create_text(px + 6, py, text=node.label,
                                            anchor="w", fill="#222222")

    def _on_wheel(self, event) -> None:
        self.zoom(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP)

    def _on_press(self, event) -> None:
        self._drag = (event.x, event.y)

    def _on_drag(self, event) -> None:
        if self._drag is None:
            return
        self._offset[0] += event.x - self._drag[0]
        self._offset[1] += event.y - self._drag[1]
        self._drag = (event.x, event.y)
        self._draw()
