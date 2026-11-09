"""ClearFrame Photo Editor - 100% Python (tkinter UI + Pillow image processing)."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageTk, ImageEnhance, ImageFilter, ImageOps

MAX_HISTORY = 25      # how many undo steps are kept
PREVIEW_MAX = 1200    # slider preview uses a smaller copy so big photos stay smooth
CANVAS_BG = "#2b2f33"

# key: (label, min, max, default, step)
ADJUSTMENTS = {
    "brightness": ("Brightness", 0.2, 2.0, 1.0, 0.05),
    "contrast":   ("Contrast",   0.2, 2.0, 1.0, 0.05),
    "color":      ("Saturation", 0.0, 2.0, 1.0, 0.05),
    "sharpness":  ("Sharpness",  0.0, 3.0, 1.0, 0.1),
    "blur":       ("Blur",       0.0, 10.0, 0.0, 0.5),
}


# ---------- filters (each takes and returns an RGB PIL image) ----------
def f_grayscale(img):
    return ImageOps.grayscale(img).convert("RGB")


def f_sepia(img):
    return ImageOps.colorize(ImageOps.grayscale(img), "#2e1f0f", "#ffecc8", mid="#9c7a52")


def f_blackwhite(img):
    return ImageOps.grayscale(img).point(lambda p: 255 if p > 128 else 0).convert("RGB")


def f_invert(img):
    return ImageOps.invert(img)


def f_warm(img):
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 1.12)))
    b = b.point(lambda i: int(i * 0.88))
    return Image.merge("RGB", (r, g, b))


def f_cool(img):
    r, g, b = img.split()
    r = r.point(lambda i: int(i * 0.88))
    b = b.point(lambda i: min(255, int(i * 1.12)))
    return Image.merge("RGB", (r, g, b))


FILTERS = {
    "Grayscale": f_grayscale,
    "Sepia": f_sepia,
    "Black & White": f_blackwhite,
    "Invert": f_invert,
    "Warm": f_warm,
    "Cool": f_cool,
    "Emboss": lambda im: im.filter(ImageFilter.EMBOSS),
    "Contour": lambda im: im.filter(ImageFilter.CONTOUR),
}


class PhotoEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClearFrame Photo Editor")
        self.geometry("1150x720")
        self.minsize(950, 600)

        self.img = None            # current committed image (full resolution)
        self.preview_src = None    # smaller copy used for live slider preview
        self.history, self.redo_stack = [], []
        self.photo = None          # keeps a reference so tkinter does not drop the image
        self.scale = 1.0
        self.box = (0, 0, 0, 0)    # where the image sits on the canvas
        self.sel = None            # crop selection in canvas coordinates
        self.drag_start = None
        self._resize_job = None
        self.vars = {}

        ttk.Style(self).theme_use("clam")
        self._build_ui()
        self._bind_keys()
        self._update_buttons()

    # ---------- interface ----------
    def _build_ui(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Open", command=self.open_image).pack(side="left", padx=2)
        ttk.Button(bar, text="Save", command=self.save_image).pack(side="left", padx=2)
        self.btn_undo = ttk.Button(bar, text="Undo", command=self.undo)
        self.btn_undo.pack(side="left", padx=(14, 2))
        self.btn_redo = ttk.Button(bar, text="Redo", command=self.redo)
        self.btn_redo.pack(side="left", padx=2)
        cmp_btn = ttk.Button(bar, text="Hold to compare")
        cmp_btn.pack(side="left", padx=(14, 2))
        cmp_btn.bind("<ButtonPress-1>", lambda e: self.show_original())
        cmp_btn.bind("<ButtonRelease-1>", lambda e: self.refresh())

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        panel = ttk.Frame(body, padding=8, width=270)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)

        # adjustments
        adj = ttk.LabelFrame(panel, text="Adjustments", padding=6)
        adj.pack(fill="x")
        for key, (label, lo, hi, default, step) in ADJUSTMENTS.items():
            var = tk.DoubleVar(value=default)
            self.vars[key] = var
            row = ttk.Frame(adj)
            row.pack(fill="x")
            ttk.Label(row, text=label, width=10).pack(side="left")
            tk.Scale(row, from_=lo, to=hi, resolution=step, orient="horizontal",
                     variable=var, length=150, highlightthickness=0,
                     command=lambda v: self.refresh()).pack(side="left", fill="x", expand=True)
        btns = ttk.Frame(adj)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Apply", command=self.apply_adjustments).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Reset sliders", command=self.reset_sliders).pack(side="left", expand=True, fill="x", padx=2)

        # filters
        flt = ttk.LabelFrame(panel, text="Filters", padding=6)
        flt.pack(fill="x", pady=8)
        for i, name in enumerate(FILTERS):
            ttk.Button(flt, text=name, command=lambda n=name: self.apply_filter(n)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        flt.columnconfigure((0, 1), weight=1)

        # transform
        tr = ttk.LabelFrame(panel, text="Transform", padding=6)
        tr.pack(fill="x")
        items = [("Rotate left", lambda: self.transform(Image.Transpose.ROTATE_90)),
                 ("Rotate right", lambda: self.transform(Image.Transpose.ROTATE_270)),
                 ("Flip horizontal", lambda: self.transform(Image.Transpose.FLIP_LEFT_RIGHT)),
                 ("Flip vertical", lambda: self.transform(Image.Transpose.FLIP_TOP_BOTTOM)),
                 ("Resize...", self.resize_dialog),
                 ("Crop selection", self.crop_selection)]
        for i, (text, cmd) in enumerate(items):
            ttk.Button(tr, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        tr.columnconfigure((0, 1), weight=1)
        ttk.Label(panel, text="Tip: drag on the image to select\nan area, then press Crop selection.",
                  foreground="#666").pack(anchor="w", pady=8)

        # canvas + status bar
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(right, bg=CANVAS_BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.status = ttk.Label(right, text="Open an image to start (Ctrl+O)", padding=4)
        self.status.pack(fill="x")
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)

    def _bind_keys(self):
        self.bind_all("<Control-o>", lambda e: self.open_image())
        self.bind_all("<Control-s>", lambda e: self.save_image())
        self.bind_all("<Control-z>", lambda e: self.undo())
        self.bind_all("<Control-y>", lambda e: self.redo())

    def _update_buttons(self):
        self.btn_undo.state(["!disabled"] if len(self.history) > 1 else ["disabled"])
        self.btn_redo.state(["!disabled"] if self.redo_stack else ["disabled"])

    # ---------- image state ----------
    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.gif"), ("All files", "*.*")])
        if not path:
            return
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Cannot open image", str(exc))
            return
        self.history, self.redo_stack = [img], []
        self._load_current()

    def save_image(self):
        if self.img is None:
            return
        self._flush()
        path = filedialog.asksaveasfilename(
            title="Save image", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WebP", "*.webp")])
        if not path:
            return
        try:
            self.img.save(path, quality=95)
            self.status.config(text=f"Saved: {path}")
        except Exception as exc:
            messagebox.showerror("Cannot save image", str(exc))

    def commit(self, new_img):
        self.history.append(new_img)
        self.history = self.history[-MAX_HISTORY:]
        self.redo_stack.clear()
        self._load_current()

    def _load_current(self):
        self.img = self.history[-1]
        p = self.img.copy()
        p.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        self.preview_src = p
        self.reset_sliders(refresh=False)
        self._clear_sel()
        self.refresh()
        self._update_buttons()

    def undo(self):
        if len(self.history) > 1:
            self.redo_stack.append(self.history.pop())
            self._load_current()

    def redo(self):
        if self.redo_stack:
            self.history.append(self.redo_stack.pop())
            self._load_current()

    # ---------- adjustments ----------
    def _has_changes(self):
        return any(abs(self.vars[k].get() - v[3]) > 1e-9 for k, v in ADJUSTMENTS.items())

    def _adjust(self, img, ratio=1.0):
        v = {k: var.get() for k, var in self.vars.items()}
        if v["brightness"] != 1.0:
            img = ImageEnhance.Brightness(img).enhance(v["brightness"])
        if v["contrast"] != 1.0:
            img = ImageEnhance.Contrast(img).enhance(v["contrast"])
        if v["color"] != 1.0:
            img = ImageEnhance.Color(img).enhance(v["color"])
        if v["sharpness"] != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(v["sharpness"])
        if v["blur"] > 0:
            img = img.filter(ImageFilter.GaussianBlur(v["blur"] * ratio))
        return img

    def apply_adjustments(self):
        if self.img is not None and self._has_changes():
            self.commit(self._adjust(self.img))

    def _flush(self):
        """Commit pending slider changes before another operation."""
        self.apply_adjustments()

    def reset_sliders(self, refresh=True):
        for k, v in ADJUSTMENTS.items():
            self.vars[k].set(v[3])
        if refresh:
            self.refresh()

    def apply_filter(self, name):
        if self.img is None:
            return
        self._flush()
        self.commit(FILTERS[name](self.img))

    # ---------- transforms ----------
    def transform(self, method):
        if self.img is None:
            return
        self._flush()
        self.commit(self.img.transpose(method))

    def resize_dialog(self):
        if self.img is None:
            return
        self._flush()
        w, h = self.img.size
        new_w = simpledialog.askinteger("Resize", "New width (px):", initialvalue=w,
                                        minvalue=1, maxvalue=20000, parent=self)
        if not new_w:
            return
        new_h = simpledialog.askinteger("Resize", "New height (px):", initialvalue=max(1, round(h * new_w / w)),
                                        minvalue=1, maxvalue=20000, parent=self)
        if new_h:
            self.commit(self.img.resize((new_w, new_h), Image.Resampling.LANCZOS))

    def crop_selection(self):
        if self.img is None:
            return
        if not self.sel:
            messagebox.showinfo("Crop", "Drag on the image to select an area first.")
            return
        self._flush()
        ox, oy = self.box[0], self.box[1]
        x0, y0, x1, y1 = [(c - o) / self.scale for c, o in zip(self.sel, (ox, oy, ox, oy))]
        W, H = self.img.size
        box = (max(0, round(x0)), max(0, round(y0)), min(W, round(x1)), min(H, round(y1)))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return
        self.commit(self.img.crop(box))

    # ---------- display ----------
    def refresh(self):
        if self.preview_src is None:
            return
        ratio = self.preview_src.width / self.img.width
        self.show(self._adjust(self.preview_src, ratio), self.img.size)

    def show_original(self):
        if self.history:
            orig = self.history[0]
            self.show(orig, orig.size, keep_geometry=True)

    def show(self, img, full_size, keep_geometry=False):
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        fw, fh = full_size
        scale = min(cw / fw, ch / fh, 1.0)
        dw, dh = max(1, int(fw * scale)), max(1, int(fh * scale))
        shown = img.resize((dw, dh), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(shown)
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self.canvas.delete("img")
        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw", tags="img")
        self.canvas.tag_lower("img")
        if not keep_geometry:
            self.scale, self.box = scale, (ox, oy, ox + dw, oy + dh)
            self.status.config(text=f"{self.img.width} x {self.img.height} px   |   Zoom {scale * 100:.0f}%")

    def _on_resize(self, event):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._after_resize)

    def _after_resize(self):
        self._clear_sel()
        self.refresh()

    # ---------- crop selection with the mouse ----------
    def _clamp(self, x, y):
        x0, y0, x1, y1 = self.box
        return min(max(x, x0), x1), min(max(y, y0), y1)

    def _press(self, e):
        if self.img is None:
            return
        self._clear_sel()
        self.drag_start = self._clamp(e.x, e.y)

    def _motion(self, e):
        if self.drag_start is None:
            return
        x, y = self._clamp(e.x, e.y)
        sx, sy = self.drag_start
        self.canvas.delete("sel")
        self.canvas.create_rectangle(sx, sy, x, y, outline="white", dash=(4, 3), width=2, tags="sel")
        self.sel = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))

    def _release(self, e):
        self.drag_start = None
        if self.sel and (self.sel[2] - self.sel[0] < 6 or self.sel[3] - self.sel[1] < 6):
            self._clear_sel()

    def _clear_sel(self):
        self.sel = None
        self.canvas.delete("sel")


if __name__ == "__main__":
    PhotoEditor().mainloop()
