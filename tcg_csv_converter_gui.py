#!/usr/bin/env python3
"""Tkinter GUI for manual TCGplayer MTG ID updates and CSV conversion."""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tcg_csv_converter import (
    DEFAULT_DB_PATH,
    convert_file,
    load_database,
    run_batch,
    run_combine_files,
    update_all_data,
)

GUI_SETTINGS_PATH = pathlib.Path("data/gui_settings.json")
CONDITION_OPTIONS = [
    "Near Mint",
    "Lightly Played",
    "Moderately Played",
    "Heavily Played",
    "Damaged",
]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TCGplayer MTG CSV Converter")
        self.geometry("920x700")
        self.minsize(860, 620)

        self.db_path_var = tk.StringVar(value=str(DEFAULT_DB_PATH))

        self.single_input_var = tk.StringVar(value="")
        self.single_output_var = tk.StringVar(value="")
        self.single_unmatched_var = tk.StringVar(value="")
        self.single_condition_var = tk.StringVar(value="Lightly Played")
        self.single_language_var = tk.StringVar(value="English")
        self.single_skip_var = tk.BooleanVar(value=True)

        self.batch_input_dir_var = tk.StringVar(value="")
        self.batch_selected_files_var = tk.StringVar(value="")
        self.batch_output_dir_var = tk.StringVar(value="batch_out")
        self.batch_pattern_var = tk.StringVar(value="*.csv")
        self.batch_condition_var = tk.StringVar(value="Lightly Played")
        self.batch_language_var = tk.StringVar(value="English")
        self.batch_skip_var = tk.BooleanVar(value=True)
        self.batch_combine_var = tk.BooleanVar(value=True)
        self.batch_dedupe_var = tk.BooleanVar(value=True)
        self.batch_combined_output_var = tk.StringVar(value="combined.tcgplayer.csv")
        self.batch_combined_unmatched_var = tk.StringVar(value="combined.unmatched.csv")

        self._load_settings()

        self._build_ui()

    def _load_settings(self) -> None:
        try:
            if not GUI_SETTINGS_PATH.exists():
                return
            with GUI_SETTINGS_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return
            output_dir = (payload.get("batch_output_dir") or "").strip()
            if output_dir:
                self.batch_output_dir_var.set(output_dir)
        except Exception:
            # Non-fatal: fall back to defaults if settings cannot be read.
            return

    def _save_settings(self) -> None:
        try:
            GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "batch_output_dir": self.batch_output_dir_var.get().strip(),
            }
            with GUI_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
        except Exception:
            # Non-fatal: app should continue even if settings cannot be written.
            return

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        db_frame = ttk.LabelFrame(root, text="Database")
        db_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 8))
        db_frame.columnconfigure(1, weight=1)

        ttk.Label(db_frame, text="DB Path:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(db_frame, textvariable=self.db_path_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6
        )
        ttk.Button(db_frame, text="Browse", command=self._choose_db_path).grid(
            row=0, column=2, sticky="e", padx=6, pady=6
        )

        ttk.Button(db_frame, text="Update All Data (New Set Release)", command=self._update_all_data).grid(
            row=1, column=0, sticky="w", padx=6, pady=(0, 8)
        )
        ttk.Label(
            db_frame,
            text="Updates TCGplayer IDs and group mappings. Runs only when you click this button.",
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 8))

        tabs = ttk.Notebook(root)
        tabs.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        single_tab = ttk.Frame(tabs, padding=10)
        batch_tab = ttk.Frame(tabs, padding=10)

        tabs.add(single_tab, text="Single File")
        tabs.add(batch_tab, text="Batch")

        self._build_single_tab(single_tab)
        self._build_batch_tab(batch_tab)

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, wrap="word", height=14)
        self.log.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def _build_single_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Input CSV:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.single_input_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_single_input).grid(
            row=0, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Output CSV:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.single_output_var).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_single_output).grid(
            row=1, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Unmatched CSV:").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.single_unmatched_var).grid(
            row=2, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_single_unmatched).grid(
            row=2, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Output Format:").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(parent, text="minimum (only supported)").grid(
            row=3, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Label(parent, text="Condition:").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.single_condition_var,
            values=CONDITION_OPTIONS,
            state="readonly",
            width=24,
        ).grid(row=4, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(parent, text="Language:").grid(row=5, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.single_language_var, width=24).grid(
            row=5, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Checkbutton(
            parent,
            text="Skip unmatched rows",
            variable=self.single_skip_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=4, pady=6)

        ttk.Button(parent, text="Convert File", command=self._convert_single).grid(
            row=7, column=0, sticky="w", padx=4, pady=10
        )

    def _build_batch_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Input Folder:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_input_dir_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_batch_input_dir).grid(
            row=0, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Selected Files:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_selected_files_var).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Pick Files", command=self._choose_batch_input_files).grid(
            row=1, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Output Folder:").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_output_dir_var).grid(
            row=2, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_batch_output_dir).grid(
            row=2, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Pattern:").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_pattern_var, width=24).grid(
            row=3, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Label(parent, text="Output Format:").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(parent, text="minimum (only supported)").grid(
            row=4, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Label(parent, text="Condition:").grid(row=5, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.batch_condition_var,
            values=CONDITION_OPTIONS,
            state="readonly",
            width=24,
        ).grid(row=5, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(parent, text="Language:").grid(row=6, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_language_var, width=24).grid(
            row=6, column=1, sticky="w", padx=4, pady=4
        )

        ttk.Checkbutton(
            parent,
            text="Skip unmatched rows",
            variable=self.batch_skip_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=4, pady=6)

        ttk.Checkbutton(
            parent,
            text="Combine all files into one output CSV (always on)",
            variable=self.batch_combine_var,
            state="disabled",
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=4, pady=4)

        ttk.Checkbutton(
            parent,
            text="Deduplicate combined rows (sum quantities)",
            variable=self.batch_dedupe_var,
        ).grid(row=9, column=0, columnspan=2, sticky="w", padx=4, pady=4)

        ttk.Label(parent, text="Combined Output CSV:").grid(row=10, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_combined_output_var).grid(
            row=10, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_batch_combined_output).grid(
            row=10, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Label(parent, text="Combined Unmatched CSV:").grid(row=11, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=self.batch_combined_unmatched_var).grid(
            row=11, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(parent, text="Browse", command=self._choose_batch_combined_unmatched).grid(
            row=11, column=2, sticky="e", padx=4, pady=4
        )

        ttk.Button(parent, text="Run Batch", command=self._run_batch).grid(
            row=12, column=0, sticky="w", padx=4, pady=10
        )

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def _run_in_background(self, label: str, fn) -> None:
        def worker() -> None:
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    fn()
                output = buffer.getvalue().strip()
                self.after(0, lambda: self._append_log(f"[{label}] Success"))
                if output:
                    for line in output.splitlines():
                        self.after(0, lambda value=line: self._append_log(value))
            except Exception as exc:
                self.after(0, lambda: self._append_log(f"[{label}] Error: {exc}"))
                self.after(0, lambda: messagebox.showerror("Error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _choose_db_path(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select Database JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=pathlib.Path(self.db_path_var.get()).name,
        )
        if path:
            self.db_path_var.set(path)

    def _choose_single_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Input CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.single_input_var.set(path)
            src = pathlib.Path(path)
            self.single_output_var.set(str(src.with_name(f"{src.stem}.tcgplayer.csv")))
            self.single_unmatched_var.set(str(src.with_name(f"{src.stem}.unmatched.csv")))

    def _choose_single_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select Output CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.single_output_var.set(path)

    def _choose_single_unmatched(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select Unmatched CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.single_unmatched_var.set(path)

    def _choose_batch_input_dir(self) -> None:
        path = filedialog.askdirectory(title="Select Batch Input Folder")
        if path:
            self.batch_input_dir_var.set(path)

    def _choose_batch_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select Batch Output Folder")
        if path:
            self.batch_output_dir_var.set(path)
            self._save_settings()

    def _choose_batch_input_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Input CSV Files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if paths:
            self.batch_selected_files_var.set(";".join(paths))

    def _choose_batch_combined_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select Combined Output CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.batch_combined_output_var.set(path)

    def _choose_batch_combined_unmatched(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select Combined Unmatched CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.batch_combined_unmatched_var.set(path)

    def _update_all_data(self) -> None:
        db_path = pathlib.Path(self.db_path_var.get().strip())
        self._append_log("[update-all] Starting update (IDs + groups)...")
        self._run_in_background("update-all", lambda: update_all_data(db_path))

    def _convert_single(self) -> None:
        input_text = self.single_input_var.get().strip()
        output_text = self.single_output_var.get().strip()
        if not input_text or not output_text:
            messagebox.showerror("Missing fields", "Input CSV and Output CSV are required.")
            return

        db_path = pathlib.Path(self.db_path_var.get().strip())
        input_path = pathlib.Path(input_text)
        output_path = pathlib.Path(output_text)
        unmatched_text = self.single_unmatched_var.get().strip()
        unmatched_path = pathlib.Path(unmatched_text) if unmatched_text else None

        def task() -> None:
            db = load_database(db_path)
            convert_file(
                db=db,
                input_path=input_path,
                output_path=output_path,
                unmatched_path=unmatched_path,
                profile="minimum",
                condition=self.single_condition_var.get().strip() or "Lightly Played",
                language=self.single_language_var.get().strip() or "English",
                skip_unmatched=self.single_skip_var.get(),
            )

        self._append_log(f"[convert] Converting {input_path}")
        self._run_in_background("convert", task)

    def _run_batch(self) -> None:
        input_dir_text = self.batch_input_dir_var.get().strip()
        selected_files_text = self.batch_selected_files_var.get().strip()
        output_dir_text = self.batch_output_dir_var.get().strip()
        combine_mode = True
        combined_output_text = self.batch_combined_output_var.get().strip()
        combined_unmatched_text = self.batch_combined_unmatched_var.get().strip()

        selected_files = [
            pathlib.Path(value.strip())
            for value in selected_files_text.split(";")
            if value.strip()
        ]

        if not selected_files and not input_dir_text:
            messagebox.showerror("Missing fields", "Select files or provide an Input Folder.")
            return

        if not combined_output_text:
            messagebox.showerror("Missing fields", "Combined Output CSV is required when combine mode is enabled.")
            return

        if not output_dir_text and not pathlib.Path(combined_output_text).is_absolute():
            messagebox.showerror(
                "Missing fields",
                "Output Folder is required when Combined Output CSV is a relative filename.",
            )
            return

        if output_dir_text:
            self._save_settings()

        db_path = pathlib.Path(self.db_path_var.get().strip())
        input_dir = pathlib.Path(input_dir_text) if input_dir_text else pathlib.Path(".")
        output_dir = pathlib.Path(output_dir_text) if output_dir_text else None
        combined_output = pathlib.Path(combined_output_text) if combined_output_text else None
        combined_unmatched = pathlib.Path(combined_unmatched_text) if combined_unmatched_text else None

        # In combine mode, treat relative combined paths as inside Output Folder.
        if combine_mode and output_dir is not None:
            if combined_output is not None and not combined_output.is_absolute():
                combined_output = output_dir / combined_output
            if combined_unmatched is not None and not combined_unmatched.is_absolute():
                combined_unmatched = output_dir / combined_unmatched

        def task() -> None:
            db = load_database(db_path)
            if selected_files:
                run_combine_files(
                    db=db,
                    input_files=selected_files,
                    combined_output_path=combined_output,
                    combined_unmatched_path=combined_unmatched,
                    profile="minimum",
                    condition=self.batch_condition_var.get().strip() or "Lightly Played",
                    language=self.batch_language_var.get().strip() or "English",
                    skip_unmatched=self.batch_skip_var.get(),
                    dedupe=self.batch_dedupe_var.get(),
                )
                return

            run_batch(
                db=db,
                input_dir=input_dir,
                output_dir=output_dir,
                pattern=self.batch_pattern_var.get().strip() or "*.csv",
                profile="minimum",
                condition=self.batch_condition_var.get().strip() or "Lightly Played",
                language=self.batch_language_var.get().strip() or "English",
                skip_unmatched=self.batch_skip_var.get(),
                combined_output_path=combined_output if combine_mode else None,
                combined_unmatched_path=combined_unmatched if combine_mode else None,
                dedupe_combined=self.batch_dedupe_var.get(),
            )

        if selected_files:
            self._append_log(f"[batch] Running combine on {len(selected_files)} selected files")
            if combined_output is not None:
                self._append_log(f"[batch] Combined output path: {combined_output}")
        else:
            self._append_log(f"[batch] Running batch in {input_dir}")
            self._append_log(f"[batch] Pattern: {self.batch_pattern_var.get().strip() or '*.csv'}")
            if combine_mode and combined_output is not None:
                self._append_log(f"[batch] Combined output path: {combined_output}")
        self._run_in_background("batch", task)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
