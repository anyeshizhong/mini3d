"""Dear ImGui presentation layer for the Mini3D editor.

The application owns scene, asset, camera, renderer, and command state. This
module owns only panel layout and transient UI state. Call ``draw`` between
``imgui.new_frame`` and ``imgui.render``; the caller owns the ImGui context and
the pygame/OpenGL backend. Standard pyimgui 2.0 has no docking support, so the
four panels use a deterministic layout that adapts to window size.

``draw(width, height, texture_id)`` returns the actual viewport image rectangle
in top-left-origin window coordinates. The texture must contain the engine's
offscreen render; its UVs are flipped here. The input router can inspect
``viewport_hovered``, ``viewport_focused``, ``keyboard_captured``,
``mouse_captured``, ``modal_open`` and ``asset_dragging`` after drawing.
"""

from pathlib import Path

import imgui
import numpy as np


class EditorUI:
    """Draw editor panels against the application command interface.

    Required application state: ``assets`` (name/path/license dictionaries),
    ``scene.root_entities``, ``selection``, ``tool``, ``render_mode``,
    ``show_grid`` and ``status``. Commands: add_asset, drop_asset, select,
    duplicate_selected, delete_selected, focus_selected, frame_all,
    reset_camera, save_scene, load_scene, import_asset, browse_model,
    cancel_model_dialog, and set_view. The app also exposes model_dialog.pending.
    Optional ``draw_viewport_overlay(draw_list, rect)`` draws the gizmos.
    An asset may provide ``preview_texture`` (an OpenGL texture name) and
    ``preview_size`` (the original image width, height). The application owns
    those textures; previews use ordinary top-left image UVs, not FBO UVs.
    """

    PAYLOAD = "MINI3D_ASSET"
    MODES = ("Lit", "Wireframe", "Unlit")
    TOOLS = (("select", "Select [Q]"), ("move", "Move [G]"),
             ("rotate", "Rotate [R]"), ("scale", "Scale [S]"), ("surface", "Surface Move"))

    def __init__(self, app):
        self.app = app
        self.viewport_rect = (0, 0, 1, 1)
        self.viewport_hovered = False
        self.viewport_focused = False
        self.keyboard_captured = False
        self.mouse_captured = False
        self.asset_dragging = False
        self.modal_open = False
        self.selected_asset = 0
        self.asset_filter = ""
        self.import_path = ""
        self.import_error = ""
        self._open_import = False
        self._open_help = False
        self._show_lighting = False
        self.lighting_error = ''
        # Lightweight task workspaces: keep engine state and commands untouched.
        self.workspace = "Arrange"
        self.assets_visible = True
        self.scene_filter = ""
        self.formation_open = False
        self._edit_item_key = None
        self.formation_rows, self.formation_columns = 5, 8
        self.formation_spacing_x, self.formation_spacing_y = 1.2, 1.4
        self._group_name_id, self._group_name = None, ""
        self._group_saved_name = ""
        self._configure_style()

    @staticmethod
    def _configure_style():
        imgui.style_colors_dark()
        style = imgui.get_style()
        style.window_rounding = 0.0
        style.child_rounding = 3.0
        style.frame_rounding = 3.0
        style.popup_rounding = 4.0
        style.grab_rounding = 3.0
        style.window_padding = (12.0, 10.0)
        style.frame_padding = (7.0, 5.0)
        style.item_spacing = (8.0, 7.0)
        style.colors[imgui.COLOR_WINDOW_BACKGROUND] = (0.105, 0.118, 0.145, 1.0)
        style.colors[imgui.COLOR_TITLE_BACKGROUND] = (0.075, 0.085, 0.108, 1.0)
        style.colors[imgui.COLOR_TITLE_BACKGROUND_ACTIVE] = (0.12, 0.15, 0.19, 1.0)
        style.colors[imgui.COLOR_FRAME_BACKGROUND] = (0.16, 0.185, 0.23, 1.0)
        style.colors[imgui.COLOR_BUTTON] = (0.18, 0.225, 0.29, 1.0)
        style.colors[imgui.COLOR_BUTTON_HOVERED] = (0.23, 0.38, 0.50, 1.0)
        style.colors[imgui.COLOR_BUTTON_ACTIVE] = (0.18, 0.48, 0.63, 1.0)
        style.colors[imgui.COLOR_HEADER] = (0.18, 0.36, 0.46, 1.0)
        style.colors[imgui.COLOR_HEADER_HOVERED] = (0.24, 0.43, 0.54, 1.0)
        style.colors[imgui.COLOR_CHECK_MARK] = (0.35, 0.78, 0.88, 1.0)

    def _call(self, command, *args, **kwargs):
        """Keep a recoverable import/file error from terminating the editor."""
        try:
            return getattr(self.app, command)(*args, **kwargs)
        except Exception as exc:
            self.app.status = f"{command.replace('_', ' ').capitalize()}: {exc}"
            return None

    @staticmethod
    def _panel(name, x, y, width, height, extra_flags=0):
        imgui.set_next_window_position(float(x), float(y))
        imgui.set_next_window_size(float(max(1, width)), float(max(1, height)))
        flags = (imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE |
                 imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_SAVED_SETTINGS)
        return imgui.begin(name, flags=flags | extra_flags)

    def draw(self, width, height, texture_id):
        """Keep the viewport large while allowing the asset shelf to collapse."""
        self.asset_dragging = False
        self.modal_open = False
        menu_height = self._menu()
        status_height = 30
        available_height = max(80, height - menu_height - status_height)
        left = min(235, max(185, width * .175)) if self.assets_visible else 0
        right = min(335, max(255, width * .24))
        # On small windows collapse the library instead of crushing the viewport.
        if width - left - right < 420:
            left = 0
        if width - right < 320:
            right = max(185, width * .34)
        center = max(1, width - left - right)
        outliner_height = max(140, available_height * .39)
        if left:
            self._assets(0, menu_height, left, available_height)
        self._viewport(left, menu_height, center, available_height, texture_id)
        self._outliner(left + center, menu_height, right, outliner_height)
        self._inspector(left + center, menu_height + outliner_height,
                        right, available_height - outliner_height)
        self._status(width, height, status_height)
        self._popups()
        self._lighting_window()
        io = imgui.get_io()
        viewport_input = self.viewport_hovered and self.viewport_focused and not imgui.is_any_item_active()
        self.keyboard_captured = bool(io.want_text_input or (io.want_capture_keyboard and not viewport_input))
        self.mouse_captured = bool(io.want_capture_mouse and not self.viewport_hovered)
        if self.modal_open:
            self.viewport_hovered = False
            self.keyboard_captured = self.mouse_captured = True
        return self.viewport_rect

    def _menu(self):
        menu_height = imgui.get_frame_height()
        if imgui.begin_main_menu_bar().opened:
            menu_height = imgui.get_window_height()
            if imgui.begin_menu("File").opened:
                if imgui.menu_item("Import model...")[0]:
                    self._call("browse_model")
                if imgui.menu_item("Import from path...")[0]:
                    self._open_import = True
                if imgui.menu_item("Save scene", "Ctrl+S")[0]:
                    self._call("save_scene")
                if imgui.menu_item("Load scene", "Ctrl+O")[0]:
                    self._call("load_scene")
                imgui.end_menu()
            if imgui.begin_menu("Edit").opened:
                if imgui.menu_item("Undo", "Ctrl+Z")[0]:
                    self._call("undo")
                if imgui.menu_item("Redo", "Ctrl+Y")[0]:
                    self._call("redo")
                if imgui.menu_item("Group selected", enabled=bool(self.app.selected_entities))[0]:
                    self._call("group_selected")
                if imgui.menu_item("Ungroup", enabled=self.app.scene.selected_group_id is not None)[0]:
                    self._call("ungroup_selected")
                selected = self.app.selection is not None
                if imgui.menu_item("Duplicate", "Ctrl+D", enabled=selected)[0]:
                    self._call("duplicate_selected")
                if imgui.menu_item("Delete", "Delete", enabled=selected)[0]:
                    self._call("delete_selected")
                imgui.end_menu()
            if imgui.begin_menu("View").opened:
                clicked, value = imgui.menu_item("Ground grid", selected=self.app.show_grid)
                if clicked:
                    self.app.show_grid = value
                if imgui.menu_item("Frame all", "Home")[0]:
                    self._call("frame_all")
                if imgui.menu_item("Focus selected", "F", enabled=self.app.selection is not None)[0]:
                    self._call("focus_selected")
                imgui.end_menu()
            if imgui.begin_menu("Add").opened:
                if imgui.menu_item("Ground Mesh")[0]:
                    self._call("add_ground_mesh")
                for index, asset in enumerate(self.app.assets):
                    if imgui.menu_item(f"{asset['name']}##add{index}")[0]:
                        self._call("add_asset", index)
                imgui.end_menu()
            if imgui.begin_menu("Camera").opened:
                for label, name, shortcut in (("Front", "front", "1"),
                                               ("Right", "right", "3"),
                                               ("Top", "top", "7")):
                    if imgui.menu_item(label, shortcut)[0]:
                        self._call("set_view", name)
                if imgui.menu_item("Reset editor camera")[0]:
                    self._call("reset_camera")
                imgui.end_menu()
            if imgui.begin_menu("Render").opened:
                for mode in self.MODES:
                    if imgui.menu_item(mode, selected=self.app.render_mode == mode)[0]:
                        self.app.render_mode = mode
                if imgui.menu_item('Lighting settings')[0]:
                    self._show_lighting = True
                imgui.end_menu()
            if imgui.begin_menu("Help").opened:
                if imgui.menu_item("Controls")[0]:
                    self._open_help = True
                imgui.end_menu()
            imgui.same_line(spacing=25)
            imgui.text_disabled("MINI3D  /  Arrange  -  Light  -  Shot")
            imgui.end_main_menu_bar()
        return menu_height

    def _assets(self, x, y, width, height):
        self._panel("Assets", x, y, width, height)
        imgui.text_disabled("MODEL LIBRARY")
        imgui.push_item_width(-1)
        _, self.asset_filter = imgui.input_text("##asset_filter", self.asset_filter, 128)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Filter by asset name")
        imgui.pop_item_width()
        if imgui.button("+ Ground Mesh", width=-1):
            self._call("add_ground_mesh")
        if imgui.button("+ Import model", width=-1):
            self._call("browse_model")
        if self.app.model_dialog.pending:
            imgui.text_wrapped("File picker is open.")
            if imgui.button("Cancel file picker", width=-1):
                self._call("cancel_model_dialog")
        imgui.separator()
        imgui.text_wrapped("Drag a model into the viewport, or double-click to add.")
        imgui.spacing()
        for index, asset in enumerate(self.app.assets):
            if self.asset_filter.casefold() not in asset["name"].casefold():
                continue
            clicked, _ = imgui.selectable(
                f"{index + 1:02d}  {asset['name']}##asset{index}",
                self.selected_asset == index,
                flags=imgui.SELECTABLE_ALLOW_DOUBLE_CLICK,
                height=30,
            )
            if clicked:
                self.selected_asset = index
                if imgui.is_mouse_double_clicked(0):
                    self._call("add_asset", index)
            if imgui.begin_drag_drop_source().dragging:
                self.asset_dragging = True
                imgui.set_drag_drop_payload(self.PAYLOAD, str(index).encode("ascii"))
                imgui.text(f"Add {asset['name']}")
                imgui.end_drag_drop_source()
            if imgui.is_item_hovered():
                imgui.begin_tooltip()
                imgui.push_text_wrap_pos(420)
                imgui.text_wrapped(asset["name"])
                imgui.text_wrapped(str(asset["path"]))
                imgui.text_wrapped(str(asset.get("license", "")))
                imgui.pop_text_wrap_pos()
                imgui.end_tooltip()
        imgui.separator()
        if self.app.assets:
            self.selected_asset = max(0, min(self.selected_asset, len(self.app.assets) - 1))
            asset = self.app.assets[self.selected_asset]
            imgui.text_wrapped(asset["name"])
            self._asset_preview(asset)
            imgui.text_disabled(Path(asset["path"]).suffix.upper().lstrip("."))
            if asset.get("description"):
                imgui.text_wrapped(str(asset["description"]))
            imgui.text_wrapped(str(asset.get("license", "")))
            if imgui.button("Add to scene", width=-1):
                self._call("add_asset", self.selected_asset)
        imgui.end()

    @staticmethod
    def _asset_preview(asset):
        """Draw only the selected preview, preserving the drag list's IDs."""
        texture = asset.get("preview_texture")
        if texture is None:
            return
        image_width, image_height = asset.get("preview_size", (160, 160))
        if image_width <= 0 or image_height <= 0:
            return
        available_width = max(1, imgui.get_content_region_available_width())
        factor = min(1.0, available_width / image_width, 160.0 / image_height)
        display_width, display_height = image_width * factor, image_height * factor
        left = imgui.get_cursor_pos_x()
        imgui.set_cursor_pos_x(left + max(0, (available_width - display_width) * 0.5))
        imgui.image(texture, display_width, display_height)
        imgui.text_disabled("Source preview")

    def _choose_workspace(self, workspace):
        """Only the presentation changes; the scene and selection remain shared."""
        if workspace == self.workspace:
            return
        self._call("finish_edit")
        if workspace != "Shot" and self.app.camera_view:
            self._call("set_camera_view", False)
        self.workspace = workspace
        self.assets_visible = workspace == "Arrange"

    def _viewport(self, x, y, width, height, texture_id):
        self._panel("Viewport", x, y, width, height,
                    imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_SCROLL_WITH_MOUSE)
        # Primary navigation is task-oriented, like dedicated workspaces in 3D editors.
        for index, name in enumerate(("Arrange", "Lighting", "Shot")):
            if index:
                imgui.same_line()
            active = self.workspace == name
            if active:
                imgui.push_style_color(imgui.COLOR_BUTTON, .18, .46, .58, 1.0)
            if imgui.button(name + "##workspace"):
                self._choose_workspace(name)
            if active:
                imgui.pop_style_color()
        imgui.same_line()
        if imgui.button("Hide library" if self.assets_visible else "Show library"):
            self.assets_visible = not self.assets_visible
        imgui.same_line()
        if imgui.button("Help ?"):
            self._open_help = True
        imgui.separator()

        if self.workspace == "Arrange":
            for index, (tool, label) in enumerate(self.TOOLS[:4]):
                if index:
                    imgui.same_line()
                active = self.app.tool == tool
                if active:
                    imgui.push_style_color(imgui.COLOR_BUTTON, .18, .46, .58, 1.0)
                if imgui.button(label):
                    self._call("finish_edit")
                    self.app.tool = tool
                if active:
                    imgui.pop_style_color()
            if width >= 750:
                imgui.same_line()
            if imgui.button("Surface Move"):
                self._call("finish_edit")
                self.app.tool = "surface"
            imgui.same_line()
            if imgui.button("Place on Surface"):
                self._call("begin_surface_placement")
            if self.app.place_selected_mode:
                imgui.text_disabled("Click a surface to place the selection. Esc cancels.")
            else:
                imgui.text_wrapped("Select an object, then drag its handles or use Place on Surface.")
            for index, space in enumerate(("world", "local")):
                if index:
                    imgui.same_line()
                if imgui.radio_button(space.title(), self.app.transform_space == space):
                    self._call("finish_edit")
                    self.app.transform_space = space
            imgui.same_line()
            imgui.push_item_width(120)
            anchor_values = ("bounds_bottom", "pivot")
            changed, anchor = imgui.combo("Anchor##drop", anchor_values.index(self.app.placement_anchor),
                                          ["Bounds Bottom", "Pivot"])
            if changed:
                self.app.placement_anchor = anchor_values[anchor]
            imgui.pop_item_width()
            imgui.same_line()
            if imgui.button("Focus [F]"):
                self._call("focus_selected")
            imgui.same_line()
            if imgui.button("Frame all"):
                self._call("frame_all")
            imgui.same_line()
            _, self.app.show_grid = imgui.checkbox("Grid", self.app.show_grid)
        elif self.workspace == "Lighting":
            imgui.text_disabled("Sun / directional light  |  Adjust X Y Z, intensity and shadows in Inspector")
            modes = ("Studio", "Scene")
            imgui.push_item_width(158)
            changed, index = imgui.combo("Preview##light", modes.index(self.app.scene.lighting_mode),
                                          ["Studio Lighting", "Scene Lighting"])
            if changed:
                self._apply_lighting(mode=modes[index])
            imgui.pop_item_width()
            imgui.same_line()
            if imgui.button("Advanced lighting..."):
                self._show_lighting = True
            imgui.same_line()
            if imgui.button("Frame all"):
                self._call("frame_all")
        else:
            if imgui.button("Create Camera From View"):
                self._call("create_camera_from_view")
            imgui.same_line()
            if imgui.button("Editor View"):
                self._call("set_camera_view", False)
            imgui.same_line()
            if imgui.button("Camera View") and self.app.shot_camera is not None:
                self._call("set_camera_view", True)
            imgui.same_line()
            if imgui.button("Capture PNG") and self.app.shot_camera is not None:
                self._call("request_capture")
            if self.app.shot_camera is None:
                imgui.text_disabled("Start in Editor View, frame the scene, then Create Camera From View.")
            else:
                lens_options = (24, 35, 50, 85)
                focal_mm = self.app.shot_camera.focal_mm
                lens_labels = [str(v) + " mm" for v in lens_options]
                lens_value = next((i for i, lens in enumerate(lens_options)
                                   if abs(lens - focal_mm) < 1e-6), len(lens_options))
                if lens_value == len(lens_options):
                    lens_labels.append("{:.1f} mm (view)".format(focal_mm))
                imgui.push_item_width(116)
                changed, index = imgui.combo("Lens##shot", lens_value,
                                              lens_labels)
                if changed and index < len(lens_options):
                    self._call("set_shot_lens", lens_options[index])
                imgui.pop_item_width()
                imgui.same_line()
                ratios = ("16:9", "3:2", "4:3", "1:1")
                imgui.push_item_width(90)
                changed, index = imgui.combo("Aspect##shot",
                                              ratios.index(self.app.shot_camera.aspect_name), list(ratios))
                if changed:
                    self._call("set_shot_aspect", ratios[index])
                imgui.pop_item_width()
                imgui.same_line()
                if imgui.button("Guides on" if self.app.composition_grid else "Guides off"):
                    self.app.composition_grid = not self.app.composition_grid
                imgui.same_line()
                imgui.text_disabled("Scene lighting in both views; Camera View keeps its saved pose.")

        imgui.separator()
        image_x, image_y = imgui.get_cursor_screen_pos()
        image_w, image_h = imgui.get_content_region_available()
        image_w, image_h = max(1, int(image_w)), max(1, int(image_h))
        if self.app.shot_camera is not None and (self.app.camera_view or self.workspace == "Shot"):
            draw_list = imgui.get_window_draw_list()
            draw_list.add_rect_filled(image_x, image_y, image_x + image_w, image_y + image_h,
                                      imgui.get_color_u32_rgba(.025, .025, .03, 1))
            image_x, image_y, image_w, image_h = self.app.shot_camera.fit_rect(
                (image_x, image_y, image_w, image_h))
            imgui.set_cursor_screen_pos((image_x, image_y))
        self.viewport_rect = (int(image_x), int(image_y), image_w, image_h)
        imgui.image(texture_id, image_w, image_h, uv0=(0, 1), uv1=(1, 0))
        self.viewport_hovered = bool(imgui.is_item_hovered())
        self.viewport_focused = bool(imgui.is_window_focused())
        overlay = getattr(self.app, "draw_viewport_overlay", None)
        if overlay is not None:
            draw_list = imgui.get_window_draw_list()
            draw_list.push_clip_rect(image_x, image_y, image_x + image_w,
                                     image_y + image_h, True)
            overlay(draw_list, self.viewport_rect)
            draw_list.pop_clip_rect()
        if not self.app.camera_view and imgui.begin_drag_drop_target().hovered:
            payload = imgui.accept_drag_drop_payload(self.PAYLOAD)
            if payload is not None:
                self._call("drop_asset", int(payload.decode("ascii")), tuple(imgui.get_mouse_pos()))
            imgui.end_drag_drop_target()
        imgui.end()

    def _apply_lighting(self, **changes):
        try:
            self.app.set_lighting(**changes)
        except ValueError as exc:
            self.lighting_error = str(exc)
            self.app.status = 'Lighting: ' + self.lighting_error
        else:
            self.lighting_error = ''
            self.app.status = 'Lighting updated'

    def _lighting_window(self):
        if not self._show_lighting:
            return
        imgui.set_next_window_size(370, 0, condition=imgui.APPEARING)
        opened, self._show_lighting = imgui.begin('Scene Lighting settings', closable=True,
            flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE | imgui.WINDOW_NO_SAVED_SETTINGS)
        if opened:
            scene = self.app.scene
            modes = ('Studio', 'Scene')
            imgui.push_item_width(220)
            changed, mode = imgui.combo('Editor preview', modes.index(scene.lighting_mode),
                                         ['Studio Lighting', 'Scene Lighting'])
            if changed:
                self._apply_lighting(mode=modes[mode])
            imgui.text_unformatted('World direction: X / Y / Z (toward light)')
            changed, direction = imgui.input_float3('##light_direction', *map(float, scene.light_dir),
                                                    format='%.4g')
            if changed:
                self._apply_lighting(mode='Scene', direction=direction)
            changed, diffuse = imgui.input_float('Direct strength', scene.diffuse, step=.05, format='%.4g')
            if changed:
                self._apply_lighting(mode='Scene', diffuse=diffuse)
            changed, ambient = imgui.input_float('Ambient strength', scene.ambient, step=.05, format='%.4g')
            if changed:
                self._apply_lighting(mode='Scene', ambient=ambient)
            imgui.pop_item_width()
            imgui.text_wrapped('Editing values previews Scene Lighting. No manual normalization needed.')
            changed, enabled = imgui.checkbox('Scene shadows', scene.shadows_enabled)
            if changed:
                try:
                    self.app.set_shadows(enabled=enabled)
                    self.lighting_error = ''
                except ValueError as exc:
                    self.lighting_error = str(exc)
            imgui.text_wrapped('Shadows apply in Scene Lighting and Shot Camera.')
            imgui.text_wrapped('Shot Camera always uses Scene Lighting.')
            if self.lighting_error:
                imgui.text_wrapped('Invalid lighting: ' + self.lighting_error)
        if imgui.is_window_hovered():
            self.viewport_hovered = False
        imgui.end()

    def _outliner(self, x, y, width, height):
        self._panel("Scene Outliner", x, y, width, height)
        roots = list(self.app.scene.root_entities)
        imgui.text_disabled(f"{len(roots)} objects  |  Shift+click for multi-select")
        imgui.text_disabled("Search objects by name")
        imgui.push_item_width(-1)
        _, self.scene_filter = imgui.input_text("##scene_filter", self.scene_filter, 128)
        imgui.pop_item_width()
        if imgui.button("Group selected"):
            self._call("group_selected")
        imgui.same_line()
        if imgui.button("Ungroup"):
            self._call("ungroup_selected")
        for group in self.app.scene.groups:
            clicked, _ = imgui.selectable(group.name + "##group" + group.group_id,
                self.app.scene.selected_group_id == group.group_id)
            if clicked:
                self._call("select_group", group.group_id)
            if imgui.is_item_hovered():
                imgui.set_tooltip("{} | {} members".format(group.group_id, len(group.member_ids)))
        imgui.separator()
        if not roots:
            imgui.text_wrapped("Add an asset to start building the scene.")
        for entity in roots:
            if self.scene_filter and self.scene_filter.casefold() not in entity.name.casefold():
                continue
            self._entity_node(entity, entity)
        if self.app.selection is not None:
            locked = self.app.selection.locked
            if imgui.button("Unlock selected" if locked else "Lock selected", width=-1):
                self._call("unlock_selected" if locked else "lock_selected")
        imgui.end()

    def _entity_node(self, entity, root):
        imgui.push_id(str(id(entity)))
        children = getattr(entity, "children", ())
        flags = imgui.TREE_NODE_OPEN_ON_ARROW | imgui.TREE_NODE_SPAN_AVAILABLE_WIDTH
        if entity.entity_id in self.app.scene.selected_ids:
            flags |= imgui.TREE_NODE_SELECTED
        if not children:
            flags |= imgui.TREE_NODE_LEAF
        name = getattr(entity, "name", "Object") or "Object"
        if not getattr(entity, "visible", True):
            name += " (hidden)"
        if getattr(entity, "locked", False):
            name += " [Locked]"
        opened = imgui.tree_node(name + "##node", flags)
        if imgui.is_item_clicked() and not imgui.is_item_toggled_open():
            self._call("select", root, bool(imgui.get_io().key_shift))
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            self._call("select", root)
            self._call("focus_selected")
        if opened:
            for child in children:
                self._entity_node(child, root)
            imgui.tree_pop()
        imgui.pop_id()

    def _record_item_edit(self, entity, attribute, changed, apply):
        """One active ImGui field (including typed values) is one command."""
        key = (entity.entity_id, attribute)
        activated = imgui.is_item_activated()
        deactivated = imgui.is_item_deactivated()
        commands = self.app.commands
        if self._edit_item_key and not commands.active_transaction:
            self._edit_item_key = None
        if (activated or changed) and self._edit_item_key != key:
            self._call("finish_edit")
            commands.begin_transaction("Inspector " + attribute)
            self._edit_item_key = key
        if changed:
            apply()
        if deactivated and self._edit_item_key == key:
            commands.commit_transaction()
            self._edit_item_key = None

    def _inspector(self, x, y, width, height):
        self._panel("Inspector", x, y, width, height)
        if self.workspace == "Lighting":
            self._inspector_lighting()
            imgui.end()
            return
        if self.workspace == "Shot":
            self._inspector_shot()
            imgui.end()
            return
        entity = self.app.selection
        if entity is None:
            imgui.text_wrapped("Select an object in the viewport or Scene Outliner to edit its transform.")
            imgui.separator()
            imgui.text_wrapped("QUICK START")
            imgui.text_wrapped("1. Add Ground Mesh or an asset from the library.")
            imgui.text_wrapped("2. Select it and use G / R / S, or edit X Y Z here.")
            imgui.text_wrapped("3. Switch to Lighting, then Shot to capture a photo.")
            imgui.end()
            return
        count = len(self.app.selected_entities)
        if count == 1 and not entity.locked:
            if imgui.button(("Hide" if self.formation_open else "Show") + " Formation tools"):
                self.formation_open = not self.formation_open
            if self.formation_open:
                imgui.push_item_width(120)
                _, self.formation_rows = imgui.input_int("Rows", self.formation_rows)
                _, self.formation_columns = imgui.input_int("Columns", self.formation_columns)
                _, self.formation_spacing_x = imgui.input_float("Spacing X", self.formation_spacing_x, format="%.3f")
                _, self.formation_spacing_y = imgui.input_float("Spacing Y", self.formation_spacing_y, format="%.3f")
                imgui.pop_item_width()
                if imgui.button("Create Formation"):
                    self._call("create_formation", self.formation_rows, self.formation_columns,
                               self.formation_spacing_x, self.formation_spacing_y)
            imgui.separator()
        if count > 1:
            imgui.text("{} selected | {} editable".format(count, len(self.app.editable_selection)))
            imgui.text_wrapped("World axes / Selection Center. Inspector shows the primary; edits apply to all editable members.")
        group = self.app.scene.find_group_by_id(self.app.scene.selected_group_id)
        if group is not None:
            if self._group_name_id != group.group_id or self._group_saved_name != group.name:
                self._group_name_id, self._group_name = group.group_id, group.name
                self._group_saved_name = group.name
            imgui.text_disabled(group.group_id)
            imgui.push_item_width(-1)
            entered, self._group_name = imgui.input_text("##group_name", self._group_name, 256,
                flags=imgui.INPUT_TEXT_ENTER_RETURNS_TRUE)
            if entered:
                self._call("rename_group", self._group_name)
            imgui.pop_item_width()
            if imgui.is_item_hovered():
                imgui.set_tooltip("Group name: press Enter to apply")
        imgui.push_id(str(id(entity)))
        imgui.push_item_width(-1)
        changed, name = imgui.input_text("##name", entity.name, 256)
        self._record_item_edit(entity, "name", changed,
                               lambda: self.app.commands.set_metadata(entity, name=name))
        imgui.pop_item_width()
        imgui.text_disabled(entity.entity_id or "Unregistered entity")
        changed, visible = imgui.checkbox("Visible", entity.visible)
        if changed:
            self.app.set_entity_metadata(entity, visible=visible)
        imgui.same_line()
        if imgui.button("Unlock" if entity.locked else "Lock"):
            self._call("unlock_selected" if entity.locked else "lock_selected")
        if entity.locked:
            imgui.text_colored("Locked - unlock to edit placement", 1.0, .75, .3)
        imgui.separator()
        imgui.text("Transform")
        imgui.text_disabled("Axis order: X / Y / Z")
        for label, attribute, values, speed in (
            ("Position", "pos", entity.pos, 0.01),
            ("Rotation (degrees)", "rot", np.degrees(entity.rot), 0.5),
            ("Scale", "scale", entity.scale, 0.01),
        ):
            imgui.text(label)
            if entity.locked:
                imgui.text_disabled(" / ".join("{:.3f}".format(value) for value in values))
                continue
            imgui.push_item_width(-1)
            changed, result = imgui.drag_float3("##" + attribute, *map(float, values),
                                                change_speed=speed, format="%.3f")
            result = np.asarray(result, dtype=np.float64)
            if attribute == "rot":
                result = np.radians(result)
            elif attribute == "scale":
                result = np.maximum(result, 0.001)
            command_attribute = {"pos": "position", "rot": "rotation", "scale": "scale"}[attribute]
            self._record_item_edit(entity, attribute, changed and np.all(np.isfinite(result)),
                                   lambda: self.app.apply_inspector_transform(entity, command_attribute, result))
            imgui.pop_item_width()
        imgui.push_text_wrap_pos(0)
        imgui.text_disabled("Ctrl+click a value to type precisely.")
        imgui.pop_text_wrap_pos()
        if self.app.tool == "scale" and self.app.transform_space == "world":
            imgui.text_wrapped("World scale projects onto local scale axes; no shear.")
        imgui.separator()
        imgui.text("Placement")
        if entity.locked:
            imgui.text_disabled(entity.placement_type + " / " + entity.placement_anchor)
        else:
            imgui.push_item_width(-1)
            types = ("prop", "character")
            changed, index = imgui.combo("##placement_type", types.index(entity.placement_type),
                                         ["Prop", "Character"])
            if changed:
                self.app.set_entity_metadata(entity, placement_type=types[index],
                                              keep_upright=types[index] == "character")
            anchors = ("bounds_bottom", "pivot")
            changed, index = imgui.combo("##entity_anchor", anchors.index(entity.placement_anchor),
                                         ["Bounds Bottom", "Pivot"])
            if changed:
                self.app.set_entity_metadata(entity, placement_anchor=anchors[index])
            imgui.pop_item_width()
            if entity.placement_type == "character":
                imgui.text_disabled("Surface placement keeps world Z upright.")
        imgui.separator()
        if imgui.button("Focus [F]"):
            self._call("focus_selected")
        imgui.same_line()
        if imgui.button("Duplicate"):
            self._call("duplicate_selected")
        if imgui.button("Delete selected", width=-1):
            self._call("delete_selected")
        path = getattr(entity, "asset_path", None)
        if path:
            imgui.separator()
            imgui.text_disabled("SOURCE ASSET")
            imgui.text_wrapped(str(path))
        imgui.pop_id()
        imgui.end()

    def _inspector_lighting(self):
        scene = self.app.scene
        from .atmosphere import atmosphere_state, sun_angles
        settings = atmosphere_state(scene)
        imgui.text("SKY / SUNSET PHOTOGRAPHY")
        if imgui.button("Golden-hour preset", width=-1):
            self._call("sunset_preset")
        if imgui.button("Photographic sunset preset", width=-1):
            self._call("sunset_preset")
            self._call("set_atmosphere",sky_texture='sunset',ground_texture='gravel',
                sky_intensity=.7,ground_scale=.4,sun_size=.53,tone_mapping='filmic',exposure_ev=-.25)
        changed, value = imgui.checkbox("Sky background", settings['enabled'])
        if changed: self._call("set_atmosphere", enabled=value)
        changed, value = imgui.checkbox("Infinite textured ground", settings['ground'])
        if changed: self._call("set_atmosphere", ground=value)
        if settings['enabled']:
            sources=['Procedural sky','Sunset HDRI','Custom HDRI']
            source=settings['sky_texture']
            index=0 if source=='procedural' else 1 if source=='sunset' else 2
            changed,value=imgui.combo('Sky source',index,sources)
            if changed and value<2: self._call('set_atmosphere',sky_texture=('procedural','sunset')[value])
            if changed and value==2: self._sky_path_input='' if index<2 else source
            path=getattr(self,'_sky_path_input','' if index<2 else source)
            changed,path=imgui.input_text('HDR file',path,4096)
            if changed:self._sky_path_input=path
            if imgui.button('Load HDRI') and path:
                self._call('set_atmosphere',sky_texture=path)
            imgui.text_disabled('Sky dome and shadows follow the same sun direction.')
            changed,value=imgui.combo('Tone curve',0 if settings['tone_mapping']=='reinhard' else 1,
                                      ['Standard','Filmic'])
            if changed:self._call('set_atmosphere',tone_mapping=('reinhard','filmic')[value])
            angles = sun_angles(scene)
            for label, key, value, low, high in (
                    ("Sun azimuth", "azimuth", angles['azimuth'], -180., 180.),
                    ("Sun elevation", "elevation", angles['elevation'], 1., 80.),
                    ("Sun temperature (K)", "sun_temperature", settings['sun_temperature'], 2000., 10000.),
                    ("Sun diameter (deg)", "sun_size", settings['sun_size'], 0., 3.),
                    ("Sky / fill strength", "sky_intensity", settings['sky_intensity'], 0., 3.),
                    ("Exposure (EV)", "exposure_ev", settings['exposure_ev'], -3., 3.),
                    ("Atmospheric haze", "haze", settings['haze'], 0., .1)):
                changed, value = imgui.slider_float(label, float(value), low, high)
                if changed: self._call("set_atmosphere", **{key:value})
        if settings['ground']:
            changed,value=imgui.combo('Ground material',0 if settings['ground_texture']=='procedural' else 1,
                                      ['Procedural sand','Photographed gravel'])
            if changed:self._call('set_atmosphere',ground_texture=('procedural','gravel')[value])
            changed, value = imgui.slider_float("Ground texture scale", settings['ground_scale'], .1, 4.)
            if changed: self._call("set_atmosphere", ground_scale=value)
            changed, value = imgui.input_float("Ground height", settings['ground_z'], step=.1)
            if changed: self._call("set_atmosphere", ground_z=value)
        imgui.separator()
        imgui.text("SUN / DIRECTIONAL LIGHT")
        imgui.text_wrapped("Direction describes where the light is, not a physical lamp position.")
        modes = ("Studio", "Scene")
        changed, index = imgui.combo("Editor preview", modes.index(scene.lighting_mode),
                                      ["Studio Lighting", "Scene Lighting"])
        if changed:
            self._apply_lighting(mode=modes[index])
        imgui.separator()
        imgui.text_disabled("Toward light - world X / Y / Z")
        changed, direction = imgui.input_float3("##sun_direction", *map(float, scene.light_dir),
                                                 format="%.3f")
        if changed:
            self._apply_lighting(mode="Scene", direction=direction)
        changed, diffuse = imgui.input_float("Direct strength", scene.diffuse,
                                               step=.05, format="%.3f")
        if changed:
            self._apply_lighting(mode="Scene", diffuse=diffuse)
        changed, ambient = imgui.input_float("Ambient strength", scene.ambient,
                                               step=.05, format="%.3f")
        if changed:
            self._apply_lighting(mode="Scene", ambient=ambient)
        changed, enabled = imgui.checkbox("Scene shadows", scene.shadows_enabled)
        if changed:
            self._call("set_shadows", enabled)
        imgui.separator()
        imgui.text_wrapped("Tip: use Scene Lighting to match the final photo. "
                           "Shot always uses Scene Lighting even if the editor uses Studio.")
        if self.lighting_error:
            imgui.text_wrapped("Lighting error: " + self.lighting_error)

    def _inspector_shot(self):
        imgui.text("PHOTO / SHOT CAMERA")
        if self.app.shot_camera is None:
            imgui.text_wrapped("1. Switch to Editor View and frame your subject.")
            imgui.text_wrapped("2. Click Create Camera From View above the viewport.")
            imgui.text_wrapped("3. Preview in Camera View, then Capture.")
            return
        shot = self.app.shot_camera
        imgui.text_disabled("Lens: {:.1f} mm".format(shot.focal_mm))
        imgui.text_disabled("Frame: {}  /  {} x {}".format(shot.aspect_name, *shot.size))
        imgui.text_disabled("Preview: " + ("Shot Camera" if self.app.camera_view else "Editor Camera"))
        imgui.separator()
        changed, enabled = imgui.checkbox('Depth of field', shot.dof_enabled)
        if changed:
            self._call('set_shot_depth_of_field', enabled=enabled)
        imgui.push_item_width(120)
        changed, distance = imgui.input_float('Focus (m)', shot.focus_distance, .1, 1, '%.3f')
        if changed:
            self._call('set_shot_depth_of_field', focus_distance=distance)
        apertures = (1.4, 2., 2.8, 4., 5.6, 8., 11., 16., 22., 32., 64.)
        labels = ['f/{:g}'.format(value) for value in apertures]
        index = next((i for i, value in enumerate(apertures) if abs(value - shot.f_number) < 1e-6), len(apertures))
        if index == len(apertures):
            labels.append('f/{:g} (custom)'.format(shot.f_number))
        changed, selected = imgui.combo('Aperture', index, labels)
        if changed and selected < len(apertures):
            self._call('set_shot_depth_of_field', f_number=apertures[selected])
        imgui.pop_item_width()
        if imgui.button('Focus selected subject', width=-1):
            self._call('focus_shot_selection')
        imgui.text_wrapped('In Camera View, click a face or any visible surface to focus. Sky and black borders keep your focus.')
        imgui.text_wrapped('Smaller f-number gives stronger blur. Focus is measured along the camera view; 1 scene unit = 1 m.')
        imgui.text_wrapped('Use Camera View to preview depth of field. Editor View stays sharp for placement.')
        imgui.separator()
        imgui.text('PHOTO COLOR')
        imgui.push_item_width(120)
        changed, kelvin = imgui.slider_float('White balance (K)', shot.white_balance_kelvin, 2000, 12000, '%.0f K')
        if changed:
            self._call('set_shot_photo_color', white_balance_kelvin=kelvin)
        from .photo_color import PRESETS
        changed, preset = imgui.combo('Color preset', PRESETS.index(shot.color_preset), list(PRESETS))
        if changed:
            self._call('set_shot_photo_color', preset=PRESETS[preset])
        imgui.pop_item_width()
        if imgui.button('Reset photo color', width=-1):
            self._call('set_shot_photo_color', white_balance_kelvin=6500., preset='Original')
        imgui.text_wrapped('Camera color changes keep the scene lights unchanged. Preview settles to full quality when you stop adjusting.')
        imgui.separator()
        if imgui.button("Preview photo", width=-1):
            self._call("set_camera_view", True)
        if imgui.button("Return to editor view", width=-1):
            self._call("set_camera_view", False)
        if imgui.button("Capture PNG", width=-1):
            self._call("request_capture")
        imgui.separator()
        imgui.text_wrapped("The shot camera is independent from the editor camera. "
                           "To change framing, return to Editor View and click "
                           "Create Camera From View again.")
        imgui.text_wrapped("Photos exclude editing grid, gizmos and selection axes.")
        if self.app.last_capture is not None:
            imgui.separator()
            imgui.text_wrapped("Last capture: " + str(self.app.last_capture))

    def _status(self, width, height, status_height):
        imgui.push_style_var(imgui.STYLE_WINDOW_PADDING, (12, 5))
        self._panel("##status", 0, height - status_height, width, status_height,
                    imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_SCROLLBAR)
        imgui.text_unformatted(str(self.app.status))
        if imgui.is_item_hovered():
            imgui.begin_tooltip()
            imgui.push_text_wrap_pos(600)
            imgui.text_wrapped(str(self.app.status))
            imgui.pop_text_wrap_pos()
            imgui.end_tooltip()
        imgui.end()
        imgui.pop_style_var()

    def _popups(self):
        if self._open_import:
            imgui.open_popup("Import model")
            self._open_import = False
        imgui.set_next_window_size(580, 0, condition=imgui.APPEARING)
        if imgui.begin_popup_modal("Import model", flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE).opened:
            self.modal_open = True
            imgui.text_wrapped("Paste the path to a local .glb, .gltf or .stl file.")
            imgui.push_item_width(540)
            _, self.import_path = imgui.input_text("##import_path", self.import_path, 4096)
            imgui.pop_item_width()
            if self.import_error:
                imgui.text_wrapped(self.import_error)
            if imgui.button("Import"):
                path = Path(self.import_path.strip().strip('"'))
                if path.suffix.lower() not in (".glb", ".gltf", ".stl"):
                    self.import_error = "Choose a .glb, .gltf or .stl model."
                elif not path.is_file():
                    self.import_error = "The file does not exist. Check its full path."
                else:
                    try:
                        self.app.import_asset(str(path.resolve()))
                        self.import_error = ""
                        imgui.close_current_popup()
                    except Exception as exc:
                        self.import_error = str(exc)
            imgui.same_line()
            if imgui.button("Cancel"):
                self.import_error = ""
                imgui.close_current_popup()
            imgui.end_popup()
        if self._open_help:
            imgui.open_popup("Editor controls")
            self._open_help = False
        if imgui.begin_popup_modal("Editor controls", flags=imgui.WINDOW_ALWAYS_AUTO_RESIZE).opened:
            self.modal_open = True
            for text in (
                "WORKFLOW: Arrange objects -> Lighting -> Shot -> Capture PNG",
                "Arrange: add assets from the left library, move using handles.",
                "Lighting: change sun direction / strength and enable shadows in Inspector.",
                "Shot: create a shot from Editor View, preview and capture a PNG.",
                "Library: toggle Show/Hide library to enlarge the viewport.",
                "Left click: select an object",
                "Drag a transform handle: edit the selected object",
                "Middle drag: orbit | Shift + middle drag: pan",
                "Mouse wheel: zoom",
                "Q: select | G: move | R: rotate | S: scale",
                "F: focus selected | Home: frame all",
                "1 / 3 / 7: front / right / top",
                "Ctrl+D: duplicate | Delete: remove selected",
                "Ctrl+Z: undo | Ctrl+Y / Ctrl+Shift+Z: redo",
                "Shift+click: toggle selection (viewport and outliner)",
                "Surface Move: drag one object; Esc cancels; release commits.",
                "Group selected / Ungroup: persistent flat ID sets, no reparenting.",
                "Ctrl+S: save scene | Ctrl+O: load scene",
                "Drag assets onto geometry or Ground; choose the placement anchor.",
                "Place on Surface: reposition selection with its saved anchor.",
                "Locked objects remain surfaces; select them in Outliner to unlock.",
            ):
                imgui.text(text)
            if imgui.button("Close"):
                imgui.close_current_popup()
            imgui.end_popup()
