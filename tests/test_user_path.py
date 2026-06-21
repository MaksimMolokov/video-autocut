"""
Автоматический прогон всего пользовательского пути (US-кейсы) с фейковым Streamlit.

Ловит: исключения в экранах, дубликаты ключей виджетов (DuplicateWidgetID),
неработающие переходы и действия (pin/exclude/include/delete/reorder/build/render).

Запуск:  python3 tests/test_user_path.py
"""
import sys, types, os, pickle, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


class _Rerun(Exception):
    pass


class _Stop(Exception):
    pass


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __delattr__(self, k):
        self.pop(k, None)


class Ctx:
    """Контейнер (column/tab/expander). Делегирует методы (.metric/.button/...)
    обратно фейковому st, чтобы `col.metric(...)` и `with col:` работали."""

    def __init__(self, st=None):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, n):
        if self._st is not None and hasattr(type(self._st), n):
            return getattr(self._st, n)
        return lambda *a, **k: None


class FakeST(types.ModuleType):
    """Достаточно полный фейк Streamlit для прогона экранов."""

    def __init__(self, name="streamlit"):
        super().__init__(name)
        self.session_state = SessionState()
        self.click = set()          # ключи/лейблы кнопок, которые «нажаты»
        self.inputs = {}            # переопределения возвратов виджетов по ключу/лейблу
        self._keys = set()
        self.reran = False
        self.errors = []

    # ── прогон одного рендера экрана ────────────────────────────────────────
    def run_screen(self, fn, name=""):
        self._keys = set()
        self.reran = False
        try:
            fn()
            return ("ok", None)
        except _Rerun:
            return ("rerun", None)
        except _Stop:
            return ("stop", None)
        except Exception as e:
            tb = traceback.format_exc()
            self.errors.append((name, repr(e), tb))
            return ("error", tb)

    def _key(self, kind, label, key):
        kk = key or f"{kind}:{label}"
        if kk in self._keys:
            raise RuntimeError(f"DuplicateWidgetID: {kk!r} (kind={kind}, label={label!r})")
        self._keys.add(kk)
        return kk

    # ── интерактивные виджеты ───────────────────────────────────────────────
    def button(self, label="", key=None, **k):
        kk = self._key("button", label, key)
        return (key in self.click) or (label in self.click) or (kk in self.click)

    def download_button(self, label="", key=None, **k):
        self._key("download", label, key)
        return False

    def checkbox(self, label="", value=False, key=None, **k):
        self._key("checkbox", label, key)
        return self.inputs.get(key, self.inputs.get(label, value))

    def toggle(self, label="", value=False, key=None, **k):
        self._key("toggle", label, key)
        return self.inputs.get(key, self.inputs.get(label, value))

    def radio(self, label="", options=(), index=0, key=None, **k):
        self._key("radio", label, key)
        opts = list(options)
        return self.inputs.get(key, self.inputs.get(label, opts[index] if opts else None))

    def selectbox(self, label="", options=(), index=0, key=None, **k):
        self._key("selectbox", label, key)
        opts = list(options)
        return self.inputs.get(key, self.inputs.get(label, opts[index] if opts else None))

    def slider(self, label="", min_value=0, max_value=10, value=None, *a, key=None, **k):
        self._key("slider", label, key)
        return self.inputs.get(key, self.inputs.get(label, value if value is not None else min_value))

    def number_input(self, label="", min_value=0, max_value=None, value=0, *a, key=None, **k):
        self._key("number", label, key)
        return self.inputs.get(key, self.inputs.get(label, value))

    def text_input(self, label="", value="", key=None, **k):
        self._key("text", label, key)
        return self.inputs.get(key, self.inputs.get(label, value))

    def text_area(self, label="", value="", key=None, **k):
        self._key("textarea", label, key)
        return self.inputs.get(key, self.inputs.get(label, value))

    def file_uploader(self, label="", key=None, **k):
        self._key("uploader", label, key)
        return None

    def color_picker(self, label="", value="#000000", key=None, **k):
        self._key("color", label, key)
        return value

    def form_submit_button(self, label="", **k):
        return label in self.click

    # ── контейнеры ──────────────────────────────────────────────────────────
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(self) for _ in range(n)]

    def tabs(self, labels, **k):
        return [Ctx(self) for _ in labels]

    def expander(self, *a, **k):
        return Ctx(self)

    def container(self, *a, **k):
        return Ctx(self)

    def form(self, *a, **k):
        return Ctx(self)

    def spinner(self, *a, **k):
        return Ctx(self)

    def empty(self, *a, **k):
        return Ctx(self)

    def status(self, *a, **k):
        return Ctx(self)

    def sidebar(self, *a, **k):
        return Ctx(self)

    # ── control flow ────────────────────────────────────────────────────────
    def rerun(self, *a, **k):
        self.reran = True
        raise _Rerun()

    def stop(self, *a, **k):
        raise _Stop()

    def cache_data(self, *a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

    def cache_resource(self, *a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

    # всё остальное (markdown, write, image, progress, ...) — no-op
    def __getattr__(self, n):
        return lambda *a, **k: None


def main():
    st = FakeST()
    sys.modules["streamlit"] = st
    # streamlit_sortables тянет реальный streamlit.components.v1 — подменяем заглушкой,
    # которая возвращает порядок без изменений (как будто перетаскивания не было).
    _sortables = types.ModuleType("streamlit_sortables")
    _sortables.sort_items = lambda items, **k: items
    sys.modules["streamlit_sortables"] = _sortables
    g = {"__name__": "notmain", "__file__": str(ROOT / "frontend/app.py")}
    exec(compile(open(ROOT / "frontend/app.py").read(), "frontend/app.py", "exec"), g)

    frags = pickle.load(open("/tmp/neo_frags5.pkl", "rb"))
    ss = st.session_state
    results = []

    def check(name, status, tb=None, extra=""):
        mark = "OK " if status == "ok" else ("→  " if status in ("rerun", "stop") else "FAIL")
        results.append((mark, name, status, extra))
        print(f"[{mark}] {name}: {status} {extra}")
        if tb and status == "error":
            print(tb)

    # ── 0. UPLOAD: ввод путей к файлам (вкладка «Отдельные файлы») ───────────
    ss.update({"screen": "upload", "project_name": "P", "video_paths": [],
               "audio_path": None, "render_state": "not_started"})
    real_paths = [f["_abs_path"] for f in frags if Path(f["_abs_path"]).is_file()]
    st.inputs = {"paths_textarea": "\n".join(real_paths)}
    st.click = {"add_paths_btn"}
    status, tb = st.run_screen(g["_screen_upload"], "upload:add_paths")
    check("upload add paths", "ok" if ss.get("video_paths") else "error", tb,
          f"videos={len(ss.get('video_paths') or [])}")
    st.click = set(); st.inputs = {}

    # базовое состояние «после анализа»
    ss.update({
        "screen": "scenes", "scene_fragments": frags, "scene_actions": {},
        "target_duration": 30, "video_concept": None, "selected_style": None,
        "selected_format": None, "project_name": "P", "enable_clip": False,
        "video_paths": [f["_abs_path"] for f in frags], "audio_path": None,
        "tl_variants": {}, "render_state": "not_started", "preview_state": "not_generated",
    })

    # ── 1. SCENES: рендер + действия pin/exclude/include ────────────────────
    check("scenes render", *st.run_screen(g["_screen_scenes"], "scenes"))
    fid0 = frags[0]["id"]
    for act_key, expect in [(f"pin_{fid0}", "pinned"), (f"excl_{fid0}", "excluded"),
                            (f"inc_{fid0}", "included")]:
        st.click = {act_key}
        status, tb = st.run_screen(g["_screen_scenes"], f"scenes:{act_key}")
        got = ss["scene_actions"].get(fid0)
        ok = (status == "rerun") and (got == expect)
        check(f"scenes action {act_key}", "ok" if ok else "error", tb,
              f"-> action={got} (expect {expect}, status={status})")
    st.click = set()

    # forbidden + возврат pin
    st.click = {f"forb_{fid0}"}
    st.run_screen(g["_screen_scenes"], "scenes:forbid")
    check("scenes forbidden", "ok" if ss["scene_actions"].get(fid0) == "forbidden" else "error",
          None, f"action={ss['scene_actions'].get(fid0)}")
    st.click = set()

    # «✓ Принять все хорошие»
    ss["scene_actions"] = {}
    st.click = {"✓ Принять все хорошие"}
    status, tb = st.run_screen(g["_screen_scenes"], "scenes:accept_all")
    n_incl = sum(1 for v in ss["scene_actions"].values() if v == "included")
    check("scenes accept-all-good", "ok" if n_incl > 0 else "error", tb, f"included={n_incl}")
    st.click = set()

    # ── 2. SCENES → CONCEPT ─────────────────────────────────────────────────
    st.click = {"Концепция ролика →"}
    status, tb = st.run_screen(g["_screen_scenes"], "scenes->concept")
    check("scenes CTA -> concept", "ok" if status == "rerun" and ss["screen"] == "concept" else "error",
          tb, f"screen={ss['screen']}")
    st.click = set()

    # ── 3. CONCEPT render + forward ─────────────────────────────────────────
    check("concept render", *st.run_screen(g["_screen_concept"], "concept"))
    st.click = {"Выбрать стиль вручную →"}
    status, tb = st.run_screen(g["_screen_concept"], "concept->style")
    check("concept -> style", "ok" if status == "rerun" and ss["screen"] == "style" else "error",
          tb, f"screen={ss['screen']}")
    st.click = set()

    # ── 4. STYLE select ─────────────────────────────────────────────────────
    check("style render", *st.run_screen(g["_screen_style"], "style"))
    st.click = {"sty_drone_smooth"}
    status, tb = st.run_screen(g["_screen_style"], "style:select")
    check("style select", "ok" if ss.get("selected_style") == "drone_smooth" else "error",
          tb, f"selected_style={ss.get('selected_style')}")
    st.click = set()

    # ── 5. FORMAT select + build timeline ───────────────────────────────────
    ss["selected_style"] = "drone_smooth"
    check("format render", *st.run_screen(g["_screen_format"], "format"))
    ss["selected_format"] = "youtube_shorts"
    try:
        g["_build_timeline"]()
        nv = {k: len(v) for k, v in ss.get("tl_variants", {}).items()}
        check("build_timeline", "ok" if ss.get("tl_variants") else "error", None, f"variants={nv}")
    except Exception:
        check("build_timeline", "error", traceback.format_exc())

    # ── 6. TIMELINE render + delete clip ────────────────────────────────────
    check("timeline render", *st.run_screen(g["_screen_timeline"], "timeline"))
    act = ss.get("tl_variant", "A")
    if ss.get("tl_variants", {}).get(act):
        before = len(ss["tl_variants"][act])
        st.click = {f"rm_{act}_0"}
        status, tb = st.run_screen(g["_screen_timeline"], "timeline:delete")
        after = len(ss["tl_variants"][act])
        check("timeline delete clip", "ok" if (status == "rerun" and after == before - 1) else "error",
              tb, f"{before}->{after}")
        st.click = set()

    # reorder ↑ (вторая позиция вверх) если ≥2 клипа
    if len(ss.get("tl_variants", {}).get(act, [])) >= 2:
        ids_before = [s["id"] for s in ss["tl_variants"][act]]
        st.click = {f"dn_{act}_0"}      # сдвинуть первый вниз
        status, tb = st.run_screen(g["_screen_timeline"], "timeline:reorder")
        ids_after = [s["id"] for s in ss["tl_variants"][act]]
        check("timeline reorder ↓", "ok" if (status == "rerun" and ids_after != ids_before) else "error",
              tb, f"{ids_before}->{ids_after}")
        st.click = set()

    # ── 7. PREVIEW + RENDER screens render (без реального ffmpeg) ────────────
    ss["preview_state"] = "not_generated"
    check("preview render", *st.run_screen(g["_screen_preview"], "preview"))
    ss["render_state"] = "not_started"
    check("render render", *st.run_screen(g["_screen_render"], "render"))

    # ── 8. UPLOAD + RESULT screens render ───────────────────────────────────
    check("upload render", *st.run_screen(g["_screen_upload"], "upload"))
    ss["render_path"] = "/tmp/x.mp4"
    check("result render", *st.run_screen(g["_screen_result"], "result"))

    # ── итог ────────────────────────────────────────────────────────────────
    fails = [r for r in results if r[0] == "FAIL"]
    print("\n" + "=" * 60)
    print(f"ИТОГ: {len(results)} проверок, провалов: {len(fails)}")
    for _, name, status, extra in fails:
        print(f"  ✗ {name}: {status} {extra}")
    if st.errors:
        print(f"\nИсключения ({len(st.errors)}):")
        for name, err, _ in st.errors:
            print(f"  ✗ {name}: {err}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
