#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Приложение для работы с файлами и SQLite базой данных.
Согласно ТЗ из README_QWEN.md
"""

import os
import sys
import csv
import uuid
import sqlite3
import hashlib
import shutil
import webbrowser
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QComboBox,
    QCheckBox, QSplitter, QGroupBox, QScrollArea, QDialog,
    QDialogButtonBox, QFormLayout, QAbstractItemView,
    QMenuBar, QMenu, QToolBar, QStatusBar, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QSize
from PyQt6.QtGui import QIcon, QAction


class FileAnalyzer(QThread):
    """Поток для анализа файлов в папке загрузки"""
    files_found = pyqtSignal(dict)
    
    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path
        self._stop_flag = False
    
    def run(self):
        """Анализ файлов в папке"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        info_extensions = {'.pdf', '.html', '.json', '.txt', '.xml', '.doc', '.docx'}
        
        images = []
        info_files = []
        
        if not os.path.exists(self.folder_path):
            self.files_found.emit([])
            return
        
        for root, dirs, files in os.walk(self.folder_path):
            if self._stop_flag:
                break
            for file in files:
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                
                if ext in image_extensions:
                    images.append(file_path)
                elif ext in info_extensions:
                    info_files.append(file_path)
        
        self.files_found.emit({'images': images, 'info_files': info_files})
    
    def stop(self):
        self._stop_flag = True


class ColumnSelectionDialog(QDialog):
    """Диалог выбора столбцов для отображения"""
    
    def __init__(self, columns: List[str], selected_columns: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор столбцов")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        
        for col in columns:
            item = QListWidgetItem(col)
            if col in selected_columns:
                item.setSelected(True)
            self.list_widget.addItem(item)
        
        layout.addWidget(QLabel("Выберите столбцы для отображения:"))
        layout.addWidget(self.list_widget)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_selected_columns(self) -> List[str]:
        return [item.text() for item in self.list_widget.selectedItems()]


class RecordEditDialog(QDialog):
    """Диалог редактирования записи (uuid_developer, slug, category_car, model)"""
    
    def __init__(self, record_data: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование записи")
        self.setMinimumWidth(500)
        self.record_data = record_data.copy()
        
        layout = QFormLayout(self)
        
        self.uuid_edit = QLineEdit(record_data.get('uuid_developer', ''))
        self.slug_edit = QLineEdit(record_data.get('slug', ''))
        self.category_edit = QLineEdit(record_data.get('category_car', ''))
        self.model_edit = QLineEdit(record_data.get('model', ''))
        
        layout.addRow("UUID разработчика:", self.uuid_edit)
        layout.addRow("Slug:", self.slug_edit)
        layout.addRow("Категория техники:", self.category_edit)
        layout.addRow("Модель:", self.model_edit)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_data(self) -> Dict:
        return {
            'uuid_developer': self.uuid_edit.text().strip(),
            'slug': self.slug_edit.text().strip(),
            'category_car': self.category_edit.text().strip(),
            'model': self.model_edit.text().strip()
        }


class MainWindow(QMainWindow):
    """Основное окно приложения"""
    
    def __init__(self):
        super().__init__()
        
        self.settings = QSettings("TechApp", "TechProcessor")
        
        # Пути к папкам
        self.download_folder = self.settings.value("download_folder", "")
        self.upload_folder = self.settings.value("upload_folder", "")
        
        # Данные из БД
        self.db_connection = None
        self.current_table = ""
        self.db_columns = []
        self.selected_db_columns = []
        self.db_data = []
        
        # CSV данные
        self.csv_data = {}  # Ключ - комбинация (file_hash или url), значение - запись
        self.csv_file_path = ""
        
        # Выбранные файлы
        self.selected_images: Set[str] = set()
        self.selected_info_files: Set[str] = set()
        
        # Хэш файлов для дедупликации
        self.file_hashes = {}  # Путь -> хэш
        
        self.init_ui()
        self.load_settings()
        self.load_csv_data()
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Обработчик технической информации")
        self.setMinimumSize(1200, 800)
        
        # Создаем меню
        self.create_menu_bar()
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Верхняя панель с выбором БД и папок
        top_group = QGroupBox("Настройки")
        top_layout = QHBoxLayout(top_group)
        
        # Выбор БД
        db_layout = QVBoxLayout()
        self.db_label = QLabel("База данных: не выбрана")
        self.db_select_btn = QPushButton("Выбрать .db файл")
        self.db_select_btn.clicked.connect(self.select_database)
        db_layout.addWidget(self.db_label)
        db_layout.addWidget(self.db_select_btn)
        top_layout.addLayout(db_layout)
        
        # Папка загрузки
        download_layout = QVBoxLayout()
        self.download_label = QLabel(f"Папка загрузки: {self.download_folder or 'не выбрана'}")
        self.download_select_btn = QPushButton("Выбрать папку загрузки")
        self.download_select_btn.clicked.connect(self.select_download_folder)
        download_layout.addWidget(self.download_label)
        download_layout.addWidget(self.download_select_btn)
        top_layout.addLayout(download_layout)
        
        # Папка выгрузки
        upload_layout = QVBoxLayout()
        self.upload_label = QLabel(f"Папка выгрузки: {self.upload_folder or 'не выбрана'}")
        self.upload_select_btn = QPushButton("Выбрать папку выгрузки")
        self.upload_select_btn.clicked.connect(self.select_upload_folder)
        upload_layout.addWidget(self.upload_label)
        upload_layout.addWidget(self.upload_select_btn)
        top_layout.addLayout(upload_layout)
        
        # Кнопка очистки папки загрузки
        clear_layout = QVBoxLayout()
        self.clear_download_btn = QPushButton("Очистить папку загрузки")
        self.clear_download_btn.clicked.connect(self.clear_download_folder)
        self.clear_download_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        clear_layout.addWidget(QLabel("Управление:"))
        clear_layout.addWidget(self.clear_download_btn)
        top_layout.addLayout(clear_layout)
        
        top_layout.addStretch()
        main_layout.addWidget(top_group)
        
        # Панель ввода данных для выгрузки
        input_group = QGroupBox("Данные для выгрузки (заполните перед обработкой)")
        input_layout = QHBoxLayout(input_group)
        
        input_layout.addWidget(QLabel("Модель:"))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Название модели")
        input_layout.addWidget(self.model_input)
        
        input_layout.addWidget(QLabel("Slug компании:"))
        self.slug_input = QLineEdit()
        self.slug_input.setPlaceholderText("slug")
        input_layout.addWidget(self.slug_input)
        
        input_layout.addWidget(QLabel("UUID компании:"))
        self.uuid_input = QLineEdit()
        self.uuid_input.setPlaceholderText("UUID")
        input_layout.addWidget(self.uuid_input)
        
        input_layout.addWidget(QLabel("Категория компании:"))
        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText("Категория")
        input_layout.addWidget(self.category_input)
        
        main_layout.addWidget(input_group)
        
        # Разделитель для основной области
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Левая панель - список файлов
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(400)
        
        # Список изображений
        img_group = QGroupBox("Изображения (папка загрузки)")
        img_layout = QVBoxLayout(img_group)
        self.image_list = QListWidget()
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        img_layout.addWidget(self.image_list)
        left_layout.addWidget(img_group)
        
        # Список информационных файлов
        info_group = QGroupBox("Инфо-файлы (PDF/HTML/JSON)")
        info_layout = QVBoxLayout(info_group)
        self.info_file_list = QListWidget()
        self.info_file_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        info_layout.addWidget(self.info_file_list)
        left_layout.addWidget(info_group)
        
        splitter.addWidget(left_panel)
        
        # Правая панель - таблица данных
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Панель управления таблицей
        table_control_layout = QHBoxLayout()
        
        self.table_select_btn = QPushButton("Выбрать таблицу")
        self.table_select_btn.clicked.connect(self.select_table)
        self.table_select_btn.setEnabled(False)
        table_control_layout.addWidget(self.table_select_btn)
        
        self.table_label = QLabel("Таблица: не выбрана")
        table_control_layout.addWidget(self.table_label)
        
        self.column_select_btn = QPushButton("Выбрать столбцы")
        self.column_select_btn.clicked.connect(self.select_columns)
        self.column_select_btn.setEnabled(False)
        table_control_layout.addWidget(self.column_select_btn)
        
        self.check_filter = QCheckBox("Показать только невыполненные (check_humane=0)")
        self.check_filter.stateChanged.connect(self.filter_table)
        self.check_filter.setEnabled(False)
        table_control_layout.addWidget(self.check_filter)
        
        table_control_layout.addStretch()
        
        self.process_btn = QPushButton("Обработать выбранные")
        self.process_btn.clicked.connect(self.process_selected)
        self.process_btn.setStyleSheet("background-color: #4ecdc4; color: white; font-weight: bold;")
        self.process_btn.setEnabled(False)
        table_control_layout.addWidget(self.process_btn)
        
        right_layout.addLayout(table_control_layout)
        
        # Таблица данных из БД
        self.db_table = QTableWidget()
        self.db_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.db_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.db_table.itemDoubleClicked.connect(self.on_item_double_clicked)
        right_layout.addWidget(self.db_table)
        
        # Нижняя панель - CSV данные для редактирования
        csv_group = QGroupBox("Данные из CSV (для редактирования)")
        csv_layout = QVBoxLayout(csv_group)
        
        self.csv_table = QTableWidget()
        self.csv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.csv_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.csv_table.itemDoubleClicked.connect(self.edit_csv_record)
        csv_layout.addWidget(self.csv_table)
        
        csv_button_layout = QHBoxLayout()
        
        self.edit_csv_btn = QPushButton("Редактировать запись")
        self.edit_csv_btn.clicked.connect(self.edit_csv_record)
        csv_button_layout.addWidget(self.edit_csv_btn)
        
        self.clear_csv_btn = QPushButton("Очистить запись")
        self.clear_csv_btn.clicked.connect(self.clear_csv_record)
        csv_button_layout.addWidget(self.clear_csv_btn)
        
        self.save_csv_btn = QPushButton("Сохранить CSV")
        self.save_csv_btn.clicked.connect(self.save_csv_data)
        self.save_csv_btn.setStyleSheet("background-color: #95e1d3; color: black; font-weight: bold;")
        csv_button_layout.addWidget(self.save_csv_btn)
        
        csv_button_layout.addStretch()
        csv_layout.addLayout(csv_button_layout)
        
        right_layout.addWidget(csv_group)
        
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(splitter)
        
        # Статус бар
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Готов к работе")
    
    def create_menu_bar(self):
        """Создание меню"""
        menubar = self.menuBar()
        
        # Файл меню
        file_menu = menubar.addMenu("Файл")
        
        save_action = QAction("Сохранить настройки", self)
        save_action.triggered.connect(self.save_settings)
        file_menu.addAction(save_action)
        
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Справка меню
        help_menu = menubar.addMenu("Справка")
        
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def load_settings(self):
        """Загрузка настроек"""
        if self.download_folder:
            self.scan_download_folder()
        
        if self.upload_folder:
            self.load_csv_data()
    
    def save_settings(self):
        """Сохранение настроек"""
        self.settings.setValue("download_folder", self.download_folder)
        self.settings.setValue("upload_folder", self.upload_folder)
        self.statusBar.showMessage("Настройки сохранены")
    
    def select_database(self):
        """Выбор SQLite базы данных"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите базу данных", "", "SQLite Files (*.db)"
        )
        
        if file_path:
            try:
                self.db_connection = sqlite3.connect(file_path)
                self.db_label.setText(f"База данных: {os.path.basename(file_path)}")
                self.table_select_btn.setEnabled(True)
                self.statusBar.showMessage(f"База данных загружена: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть базу данных: {e}")
    
    def select_table(self):
        """Выбор таблицы из БД"""
        if not self.db_connection:
            return
        
        cursor = self.db_connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        if not tables:
            QMessageBox.warning(self, "Предупреждение", "В базе данных нет таблиц")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Выберите таблицу")
        layout = QVBoxLayout(dialog)
        
        combo = QComboBox()
        combo.addItems(tables)
        layout.addWidget(combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_table = combo.currentText()
            self.table_label.setText(f"Таблица: {self.current_table}")
            self.load_table_data()
            self.column_select_btn.setEnabled(True)
            self.check_filter.setEnabled(True)
    
    def load_table_data(self):
        """Загрузка данных из таблицы"""
        if not self.db_connection or not self.current_table:
            return
        
        cursor = self.db_connection.cursor()
        cursor.execute(f"PRAGMA table_info({self.current_table});")
        self.db_columns = [row[1] for row in cursor.fetchall()]
        
        # По умолчанию выбираем все столбцы
        if not self.selected_db_columns:
            self.selected_db_columns = self.db_columns.copy()
        
        self.refresh_table_display()
    
    def select_columns(self):
        """Выбор столбцов для отображения"""
        if not self.db_columns:
            return
        
        dialog = ColumnSelectionDialog(self.db_columns, self.selected_db_columns, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.get_selected_columns()
            if selected:
                self.selected_db_columns = selected
                self.refresh_table_display()
    
    def refresh_table_display(self):
        """Обновление отображения таблицы"""
        if not self.db_connection or not self.current_table:
            return
        
        # Проверка наличия обязательных столбцов
        required_columns = {'url_item', 'url_pagination', 'check_humane'}
        available_columns = set(self.db_columns)
        
        if not required_columns.issubset(available_columns):
            missing = required_columns - available_columns
            QMessageBox.warning(
                self, "Предупреждение",
                f"В таблице отсутствуют обязательные столбцы: {missing}"
            )
            return
        
        cursor = self.db_connection.cursor()
        
        # Формируем запрос с выбранными столбцами
        columns_str = ', '.join(self.selected_db_columns)
        query = f"SELECT {columns_str} FROM {self.current_table}"
        
        # Применяем фильтр по check_humane если нужно
        if self.check_filter.isChecked():
            query += " WHERE check_humane = 0"
        
        cursor.execute(query)
        self.db_data = cursor.fetchall()
        
        # Заполняем таблицу
        self.db_table.setColumnCount(len(self.selected_db_columns))
        self.db_table.setHorizontalHeaderLabels(self.selected_db_columns)
        self.db_table.setRowCount(len(self.db_data))
        
        for row_idx, row_data in enumerate(self.db_data):
            for col_idx, value in enumerate(row_data):
                item = QTableWidgetItem(str(value) if value is not None else "")
                # Делаем ячейки редактируемыми для копирования
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.db_table.setItem(row_idx, col_idx, item)
        
        # Авто-размер колонок
        self.db_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        
        self.process_btn.setEnabled(len(self.db_data) > 0)
    
    def filter_table(self):
        """Фильтрация таблицы по check_humane"""
        self.refresh_table_display()
    
    def on_item_double_clicked(self, item: QTableWidgetItem):
        """Обработка двойного клика по ячейке - открытие URL"""
        row = item.row()
        column_name = self.selected_db_columns[item.column()]
        
        if column_name in ('url_item', 'url_pagination'):
            url = item.text()
            if url:
                webbrowser.open(url)
    
    def select_download_folder(self):
        """Выбор папки загрузки"""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку загрузки")
        if folder:
            self.download_folder = folder
            self.download_label.setText(f"Папка загрузки: {folder}")
            self.scan_download_folder()
            self.save_settings()
    
    def scan_download_folder(self):
        """Сканирование папки загрузки"""
        if not self.download_folder:
            return
        
        self.statusBar.showMessage(f"Сканирование папки: {self.download_folder}")
        
        self.analyzer = FileAnalyzer(self.download_folder)
        self.analyzer.files_found.connect(self.on_files_analyzed)
        self.analyzer.start()
    
    def on_files_analyzed(self, result: dict):
        """Обработка результатов анализа файлов"""
        self.image_list.clear()
        self.info_file_list.clear()
        
        images = result.get('images', [])
        info_files = result.get('info_files', [])
        
        for img_path in images:
            item = QListWidgetItem(os.path.basename(img_path))
            item.setData(Qt.ItemDataRole.UserRole, img_path)
            self.image_list.addItem(item)
        
        for info_path in info_files:
            item = QListWidgetItem(os.path.basename(info_path))
            item.setData(Qt.ItemDataRole.UserRole, info_path)
            self.info_file_list.addItem(item)
        
        self.statusBar.showMessage(
            f"Найдено: {len(images)} изображений, {len(info_files)} инфо-файлов"
        )
    
    def select_upload_folder(self):
        """Выбор папки выгрузки"""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку выгрузки")
        if folder:
            self.upload_folder = folder
            self.upload_label.setText(f"Папка выгрузки: {folder}")
            self.load_csv_data()
            self.save_settings()
    
    def get_csv_path(self) -> str:
        """Получение пути к CSV файлу"""
        if not self.upload_folder:
            return ""
        return os.path.join(self.upload_folder, "data.csv")
    
    def load_csv_data(self):
        """Загрузка данных из CSV"""
        csv_path = self.get_csv_path()
        if not os.path.exists(csv_path):
            return
        
        self.csv_file_path = csv_path
        self.csv_data = {}
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Ключ - комбинация url_item + url_pagination для уникальности
                    key = (row.get('url_item', ''), row.get('url_pagination', ''))
                    self.csv_data[key] = row
            
            self.refresh_csv_table()
        except Exception as e:
            QMessageBox.warning(self, "Предупреждение", f"Ошибка загрузки CSV: {e}")
    
    def refresh_csv_table(self):
        """Обновление таблицы CSV"""
        headers = ['uuid_developer', 'slug', 'category_car', 'model', 
                   'file_name', 'photo', 'url_item', 'url_pagination']
        
        self.csv_table.setColumnCount(len(headers))
        self.csv_table.setHorizontalHeaderLabels(headers)
        self.csv_table.setRowCount(len(self.csv_data))
        
        for row_idx, (key, data) in enumerate(self.csv_data.items()):
            for col_idx, header in enumerate(headers):
                value = data.get(header, '')
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.csv_table.setItem(row_idx, col_idx, item)
        
        self.csv_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
    
    def edit_csv_record(self):
        """Редактирование записи из CSV"""
        current_row = self.csv_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Предупреждение", "Выберите запись для редактирования")
            return
        
        # Получаем данные из текущей строки
        record_data = {}
        headers = ['uuid_developer', 'slug', 'category_car', 'model',
                   'file_name', 'photo', 'url_item', 'url_pagination']
        
        for col_idx, header in enumerate(headers):
            item = self.csv_table.item(current_row, col_idx)
            record_data[header] = item.text() if item else ''
        
        dialog = RecordEditDialog(record_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            
            # Обновляем данные
            key = (record_data.get('url_item', ''), record_data.get('url_pagination', ''))
            if key in self.csv_data:
                self.csv_data[key].update(new_data)
                self.refresh_csv_table()
                self.statusBar.showMessage("Запись обновлена")
    
    def clear_csv_record(self):
        """Очистка записи из CSV"""
        current_row = self.csv_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Предупреждение", "Выберите запись для очистки")
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Вы уверены, что хотите очистить эту запись?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            headers = ['uuid_developer', 'slug', 'category_car', 'model']
            for col_idx, header in enumerate(headers):
                item = self.csv_table.item(current_row, col_idx)
                if item:
                    item.setText('')
            
            # Обновляем в данных
            key = None
            for k, v in self.csv_data.items():
                if v.get('url_item') == self.csv_table.item(current_row, 6).text() and \
                   v.get('url_pagination') == self.csv_table.item(current_row, 7).text():
                    key = k
                    break
            
            if key:
                for header in headers:
                    self.csv_data[key][header] = ''
    
    def save_csv_data(self):
        """Сохранение данных в CSV"""
        if not self.upload_folder:
            QMessageBox.warning(self, "Предупреждение", "Выберите папку выгрузки")
            return
        
        csv_path = self.get_csv_path()
        headers = ['uuid_developer', 'slug', 'category_car', 'model',
                   'file_name', 'photo', 'url_item', 'url_pagination']
        
        try:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                for row in self.csv_data.values():
                    writer.writerow({h: row.get(h, '') for h in headers})
            
            QMessageBox.information(self, "Успех", f"CSV файл сохранен: {csv_path}")
            self.statusBar.showMessage("CSV данные сохранены")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения CSV: {e}")
    
    def get_file_hash(self, file_path: str) -> str:
        """Вычисление хэша файла для дедупликации"""
        if file_path in self.file_hashes:
            return self.file_hashes[file_path]
        
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()
            self.file_hashes[file_path] = file_hash
            return file_hash
        except Exception:
            return ""
    
    def process_selected(self):
        """Обработка выбранных файлов и записей"""
        current_row = self.db_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Предупреждение", "Выберите запись из таблицы БД")
            return
        
        # Получаем URL из выбранной строки
        url_item = ""
        url_pagination = ""
        
        for col_idx, col_name in enumerate(self.selected_db_columns):
            item = self.db_table.item(current_row, col_idx)
            if item:
                if col_name == 'url_item':
                    url_item = item.text()
                elif col_name == 'url_pagination':
                    url_pagination = item.text()
        
        if not url_item and not url_pagination:
            QMessageBox.warning(self, "Предупреждение", 
                              "В выбранной записи нет url_item или url_pagination")
            return
        
        # Получаем выбранные файлы
        selected_image_paths = []
        for item in self.image_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                selected_image_paths.append(path)
        
        selected_info_paths = []
        for item in self.info_file_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                selected_info_paths.append(path)
        
        if not selected_image_paths and not selected_info_paths:
            QMessageBox.information(
                self, "Информация",
                "Выберите файлы для обработки (изображения или инфо-файлы)"
            )
            return
        
        # Обрабатываем файлы
        self.distribute_files(
            url_item, url_pagination,
            selected_image_paths, selected_info_paths
        )
    
    def distribute_files(self, url_item: str, url_pagination: str,
                        image_paths: List[str], info_paths: List[str]):
        """Распределение файлов по папкам выгрузки"""
        if not self.upload_folder:
            QMessageBox.warning(self, "Предупреждение", "Выберите папку выгрузки")
            return
        
        # Получаем данные из полей ввода
        model = self.model_input.text().strip()
        slug = self.slug_input.text().strip()
        company_uuid = self.uuid_input.text().strip()
        category = self.category_input.text().strip()
        
        # Проверяем заполненность обязательных полей
        if not company_uuid:
            QMessageBox.warning(
                self, "Предупреждение",
                "Заполните поле 'UUID компании' перед обработкой"
            )
            return
        
        # Создаем ключ для поиска существующей записи
        key = (url_item, url_pagination)
        
        # Проверяем существующие данные
        existing_data = self.csv_data.get(key, {})
        existing_uuid = existing_data.get('uuid_developer', '')
        
        # Используем UUID из поля ввода или из существующей записи
        record_uuid = company_uuid if company_uuid else (existing_uuid if existing_uuid else str(uuid.uuid4()))
        
        # Пути к папкам
        files_folder = os.path.join(self.upload_folder, "files")
        photos_folder = os.path.join(self.upload_folder, "photos")
        
        os.makedirs(files_folder, exist_ok=True)
        os.makedirs(photos_folder, exist_ok=True)
        
        # Обработка информационных файлов
        processed_info_files = []
        for info_path in info_paths:
            file_hash = self.get_file_hash(info_path)
            
            # Проверяем дедупликацию по хэшу
            is_duplicate = False
            existing_uuid_for_hash = None
            
            for other_key, other_data in self.csv_data.items():
                other_file_name = other_data.get('file_name', '')
                # Простая проверка - если такой файл уже есть с другим UUID
                # В реальном приложении нужна более сложная логика
                if other_file_name and os.path.basename(info_path) == os.path.basename(other_file_name):
                    existing_uuid_for_hash = other_data.get('uuid_developer', '')
                    if existing_uuid_for_hash:
                        is_duplicate = True
                        break
            
            if is_duplicate and existing_uuid_for_hash:
                # Используем существующий UUID
                record_uuid = existing_uuid_for_hash
                processed_info_files.append(os.path.basename(info_path))
            else:
                # Копируем файл
                target_folder = os.path.join(files_folder, record_uuid)
                os.makedirs(target_folder, exist_ok=True)
                target_path = os.path.join(target_folder, os.path.basename(info_path))
                
                try:
                    shutil.copy2(info_path, target_path)
                    processed_info_files.append(os.path.basename(info_path))
                except Exception as e:
                    QMessageBox.warning(
                        self, "Предупреждение",
                        f"Ошибка копирования файла {info_path}: {e}"
                    )
        
        # Обработка изображений
        processed_photos = []
        for img_path in image_paths:
            file_hash = self.get_file_hash(img_path)
            
            # Проверяем дедупликацию
            is_duplicate = False
            existing_uuid_for_hash = None
            
            for other_key, other_data in self.csv_data.items():
                other_photo = other_data.get('photo', '')
                if other_photo and os.path.basename(img_path) == os.path.basename(other_photo):
                    existing_uuid_for_hash = other_data.get('uuid_developer', '')
                    if existing_uuid_for_hash:
                        is_duplicate = True
                        break
            
            if is_duplicate and existing_uuid_for_hash:
                record_uuid = existing_uuid_for_hash
                processed_photos.append(os.path.basename(img_path))
            else:
                # Копируем изображение
                target_folder = os.path.join(photos_folder, record_uuid)
                os.makedirs(target_folder, exist_ok=True)
                target_path = os.path.join(target_folder, os.path.basename(img_path))
                
                try:
                    shutil.copy2(img_path, target_path)
                    processed_photos.append(os.path.basename(img_path))
                except Exception as e:
                    QMessageBox.warning(
                        self, "Предупреждение",
                        f"Ошибка копирования изображения {img_path}: {e}"
                    )
        
        # Обновляем CSV данные с учетом введенных значений
        file_name_str = '; '.join(processed_info_files) if processed_info_files else ''
        photo_str = '; '.join(processed_photos) if processed_photos else ''
        
        if key not in self.csv_data:
            self.csv_data[key] = {
                'uuid_developer': record_uuid,
                'slug': slug,
                'category_car': category,
                'model': model,
                'file_name': file_name_str,
                'photo': photo_str,
                'url_item': url_item,
                'url_pagination': url_pagination
            }
        else:
            # Обновляем существующую запись
            self.csv_data[key]['uuid_developer'] = record_uuid
            # Обновляем поля из инпутов если они заполнены
            if slug:
                self.csv_data[key]['slug'] = slug
            if category:
                self.csv_data[key]['category_car'] = category
            if model:
                self.csv_data[key]['model'] = model
            
            if file_name_str:
                existing = self.csv_data[key].get('file_name', '')
                if existing:
                    self.csv_data[key]['file_name'] = existing + '; ' + file_name_str
                else:
                    self.csv_data[key]['file_name'] = file_name_str
            
            if photo_str:
                existing = self.csv_data[key].get('photo', '')
                if existing:
                    self.csv_data[key]['photo'] = existing + '; ' + photo_str
                else:
                    self.csv_data[key]['photo'] = photo_str
        
        self.refresh_csv_table()
        self.statusBar.showMessage(
            f"Обработано файлов: {len(processed_info_files)} инфо-файлов, "
            f"{len(processed_photos)} изображений"
        )
    
    def clear_download_folder(self):
        """Очистка папки загрузки"""
        if not self.download_folder:
            QMessageBox.warning(self, "Предупреждение", "Папка загрузки не выбрана")
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Вы уверены, что хотите очистить папку загрузки?\n{self.download_folder}\n\n"
            "Все файлы будут удалены!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                for filename in os.listdir(self.download_folder):
                    file_path = os.path.join(self.download_folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        print(f"Ошибка удаления {file_path}: {e}")
                
                self.scan_download_folder()
                self.statusBar.showMessage("Папка загрузки очищена")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка очистки папки: {e}")
    
    def show_about(self):
        """Показать информацию о программе"""
        QMessageBox.about(
            self, "О программе",
            "Приложение для обработки технической информации\n\n"
            "Версия: 1.0\n"
            "Разработано согласно ТЗ"
        )
    
    def closeEvent(self, event):
        """Обработка закрытия приложения"""
        self.save_settings()
        if self.analyzer and hasattr(self, 'analyzer'):
            self.analyzer.stop()
            self.analyzer.wait()
        if self.db_connection:
            self.db_connection.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
