# -*- coding: utf-8 -*-
"""
Gas Inventory System v0.2.3 API Format
- PySide6 기반 가스병 재고관리 GUI 초안
- 서버 연동 전, 화면/구조 확인용 버전
- 품목/장소/상태/요약카드/재고표/최근입출고내역/차트 시안 포함
- v0.1.1: 콤보박스 드롭다운 화살표를 현재 GUI 톤에 맞게 커스텀
- v0.1.2: 현재 재고현황을 장소별 구역으로 분리 표시
- v0.1.3: 입고/출고 입력창 개선, 출고 납품회사/선명/아세틸렌 용기번호 입력 추가
- v0.1.4: 재고 현황 탭 전용 화면 추가, 상세 재고/아세틸렌 용기번호/주의 재고 구성
- v0.1.5: 입출고 내역 탭 전용 화면 추가, 이력 조회/상세/취소처리/엑셀 버튼 구성
- v0.1.6: 입출고 내역을 입출고 내역으로 명칭 변경, 검색 자동완성/검색결과 강조 표시 추가

실행:
    pip install PySide6
    python gas_inventory_v0_1_gui_preview.py
"""

import sys
import json
import sqlite3
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QSizePolicy, QSpacerItem, QDialog,
    QStackedWidget, QCompleter,
    QFormLayout, QSpinBox, QTextEdit, QMessageBox, QListWidget, QListWidgetItem
)


APP_VERSION = "0.2.3"


@dataclass
class InventoryRow:
    item: str
    item_sub: str
    location: str
    full: int
    empty: int
    repair: int
    disposal: int


class PieChartWidget(QWidget):
    def __init__(self, values, labels, colors, parent=None):
        super().__init__(parent)
        self.values = values
        self.labels = labels
        self.colors = colors
        self.setMinimumSize(230, 210)

    def paintEvent(self, event):
        total = sum(self.values) or 1
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect_size = min(self.width(), self.height() - 20) - 34
        x = 20
        y = 18
        rect = self.rect()
        pie_rect_x = x
        pie_rect_y = y
        pie_rect_size = rect_size

        start_angle = 90 * 16
        for value, color in zip(self.values, self.colors):
            span_angle = int(-360 * 16 * value / total)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.NoPen)
            painter.drawPie(pie_rect_x, pie_rect_y, pie_rect_size, pie_rect_size, start_angle, span_angle)
            start_angle += span_angle

        # donut center
        center_color = QColor("#ffffff")
        painter.setBrush(QBrush(center_color))
        painter.setPen(Qt.NoPen)
        inner = int(pie_rect_size * 0.54)
        ix = pie_rect_x + (pie_rect_size - inner) // 2
        iy = pie_rect_y + (pie_rect_size - inner) // 2
        painter.drawEllipse(ix, iy, inner, inner)

        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
        painter.drawText(ix, iy + inner // 2 - 9, inner, 20, Qt.AlignCenter, "전체")
        painter.setFont(QFont("Malgun Gothic", 17, QFont.Bold))
        painter.drawText(ix, iy + inner // 2 + 8, inner, 28, Qt.AlignCenter, f"{total} 병")

        # legend
        lx = pie_rect_x + pie_rect_size + 20
        ly = 45
        painter.setFont(QFont("Malgun Gothic", 9))
        for idx, (label, value, color) in enumerate(zip(self.labels, self.values, self.colors)):
            percent = value / total * 100
            yy = ly + idx * 32
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(lx, yy, 10, 10)
            painter.setPen(QColor("#475569"))
            painter.drawText(lx + 18, yy - 5, 130, 24, Qt.AlignVCenter, f"{label}   {value} ({percent:.1f}%)")


class Card(QFrame):
    def __init__(self, title, value, subtitle, accent="#3b82f6", icon="●"):
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumHeight(118)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("CardTitle")
        title_lbl.setStyleSheet(f"color: {accent};")

        value_lbl = QLabel(value)
        value_lbl.setObjectName("CardValue")

        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setObjectName("CardSub")

        left.addWidget(title_lbl)
        left.addWidget(value_lbl)
        left.addWidget(subtitle_lbl)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("CardIcon")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"color: {accent}; background: {accent}18; border-radius: 18px;")

        layout.addLayout(left, 1)
        layout.addWidget(icon_lbl, 0)


class SideButton(QPushButton):
    def __init__(self, text, active=False):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(active)
        self.setMinimumHeight(48)
        self.setObjectName("SideButtonActive" if active else "SideButton")


class StockChangeDialog(QDialog):
    def __init__(self, items, locations, parent=None):
        super().__init__(parent)
        self.setWindowTitle("입고 / 출고 입력")
        self.setMinimumWidth(560)
        self.setMinimumHeight(620)
        self.items = items
        self.locations = locations

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("입고 / 출고 입력")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        desc = QLabel("입고는 공급처 중심으로, 출고는 납품회사와 선명까지 남길 수 있도록 구성했습니다.")
        desc.setObjectName("DialogDesc")
        layout.addWidget(desc)

        # 작업 선택 탭 느낌 버튼
        mode_row = QHBoxLayout()
        self.in_btn = QPushButton("입고")
        self.out_btn = QPushButton("출고")
        self.move_btn = QPushButton("상태/장소 변경")
        for btn in [self.in_btn, self.out_btn, self.move_btn]:
            btn.setCheckable(True)
            btn.setMinimumHeight(42)
            mode_row.addWidget(btn)
        self.in_btn.setObjectName("ModeButtonActive")
        self.out_btn.setObjectName("ModeButton")
        self.move_btn.setObjectName("ModeButton")
        self.in_btn.setChecked(True)
        layout.addLayout(mode_row)

        self.current_mode = "입고"
        self.in_btn.clicked.connect(lambda: self.set_mode("입고"))
        self.out_btn.clicked.connect(lambda: self.set_mode("출고"))
        self.move_btn.clicked.connect(lambda: self.set_mode("상태/장소 변경"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(12)

        self.item_combo = QComboBox()
        self.item_combo.addItems(items)
        self.item_combo.currentTextChanged.connect(self.update_acetylene_box)

        self.location_combo = QComboBox()
        self.location_combo.addItems(locations)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["실병", "공병", "리페어", "폐기"])

        self.to_location_label = QLabel("변경 후 장소")
        self.to_location_combo = QComboBox()
        self.to_location_combo.addItems(locations)

        self.to_status_label = QLabel("변경 후 상태")
        self.to_status_combo = QComboBox()
        self.to_status_combo.addItems(["실병", "공병", "리페어", "폐기"])

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 9999)
        self.qty_spin.setValue(1)

        self.company_input = QLineEdit()
        self.company_input.setPlaceholderText("예: 공급업체명 또는 납품 회사명")

        self.ship_input = QLineEdit()
        self.ship_input.setPlaceholderText("예: 선명 입력")
        self.ship_input.setVisible(False)

        self.ship_label = QLabel("선명")
        self.ship_label.setVisible(False)

        self.acetylene_numbers = QTextEdit()
        self.acetylene_numbers.setPlaceholderText("아세틸렌 용기번호를 한 줄에 하나씩 입력\n예:\nA-1023\nA-1024\nA-1025")
        self.acetylene_numbers.setFixedHeight(92)

        self.acetylene_hint = QLabel("※ 아세틸렌은 입고/출고 시 용기번호를 남기도록 구성했습니다.")
        self.acetylene_hint.setObjectName("HintText")

        self.memo = QTextEdit()
        self.memo.setPlaceholderText("추가 메모를 입력하세요.")
        self.memo.setFixedHeight(72)

        form.addRow("품목", self.item_combo)
        form.addRow("현재 장소", self.location_combo)
        form.addRow("현재 상태", self.status_combo)
        form.addRow(self.to_location_label, self.to_location_combo)
        form.addRow(self.to_status_label, self.to_status_combo)
        form.addRow("수량", self.qty_spin)
        form.addRow("회사", self.company_input)
        form.addRow(self.ship_label, self.ship_input)
        form.addRow("아세틸렌 용기번호", self.acetylene_numbers)
        form.addRow("", self.acetylene_hint)
        form.addRow("메모", self.memo)

        layout.addLayout(form)

        self.preview_box = QFrame()
        self.preview_box.setObjectName("PreviewBox")
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        self.preview_title = QLabel("입력 요약")
        self.preview_title.setObjectName("PreviewTitle")
        self.preview_text = QLabel("")
        self.preview_text.setObjectName("PreviewText")
        self.preview_text.setWordWrap(True)
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(self.preview_box)

        for widget in [
            self.item_combo, self.location_combo, self.status_combo,
            self.to_location_combo, self.to_status_combo, self.qty_spin,
            self.company_input, self.ship_input, self.acetylene_numbers, self.memo
        ]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self.update_preview)
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.update_preview)
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self.update_preview)

        self.acetylene_numbers.textChanged.connect(self.update_preview)
        self.memo.textChanged.connect(self.update_preview)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("취소")
        cancel.setObjectName("GhostButton")
        ok = QPushButton("저장")
        ok.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.on_save_clicked)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

        self.result_data = None
        self.set_mode("입고")
        self.update_acetylene_box()
        self.update_preview()


    def collect_data(self):
        cylinders = [
            x.strip() for x in self.acetylene_numbers.toPlainText().splitlines()
            if x.strip()
        ]
        return {
            "mode": self.current_mode,
            "item": self.item_combo.currentText(),
            "location": self.location_combo.currentText(),
            "status": self.status_combo.currentText(),
            "to_location": self.to_location_combo.currentText(),
            "to_status": self.to_status_combo.currentText(),
            "qty": int(self.qty_spin.value()),
            "company": self.company_input.text().strip(),
            "ship": self.ship_input.text().strip(),
            "cylinders": cylinders,
            "memo": self.memo.toPlainText().strip(),
        }

    def on_save_clicked(self):
        data = self.collect_data()

        if not data["company"]:
            if data["mode"] == "출고":
                QMessageBox.warning(self, "입력 확인", "출고 시 납품회사명을 입력해주세요.")
            elif data["mode"] == "입고":
                QMessageBox.warning(self, "입력 확인", "입고 시 공급처/입고처를 입력해주세요.")
            else:
                QMessageBox.warning(self, "입력 확인", "관련 내용 또는 변경 사유를 입력해주세요.")
            return

        if data["mode"] == "출고" and not data["ship"]:
            QMessageBox.warning(self, "입력 확인", "출고 시 선명을 입력해주세요.")
            return

        if data["item"] == "아세틸렌":
            if not data["cylinders"]:
                QMessageBox.warning(self, "입력 확인", "아세틸렌은 용기번호를 한 줄에 하나씩 입력해주세요.")
                return
            if len(data["cylinders"]) != data["qty"]:
                QMessageBox.warning(
                    self,
                    "수량 확인",
                    f"수량은 {data['qty']}병인데 용기번호는 {len(data['cylinders'])}개입니다.\\n"
                    "수량과 용기번호 개수를 맞춰주세요."
                )
                return

        self.result_data = data
        self.accept()

    def set_mode(self, mode):
        self.current_mode = mode
        for btn, value in [(self.in_btn, "입고"), (self.out_btn, "출고"), (self.move_btn, "상태/장소 변경")]:
            btn.setChecked(value == mode)
            btn.setObjectName("ModeButtonActive" if value == mode else "ModeButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        is_move_mode = mode == "상태/장소 변경"
        self.to_location_label.setVisible(is_move_mode)
        self.to_location_combo.setVisible(is_move_mode)
        self.to_status_label.setVisible(is_move_mode)
        self.to_status_combo.setVisible(is_move_mode)

        if mode == "입고":
            self.company_input.setPlaceholderText("예: 공급업체명")
            self.ship_input.setVisible(False)
            self.ship_label.setVisible(False)
        elif mode == "출고":
            self.company_input.setPlaceholderText("예: 납품 회사명 / 선박대리점 / 거래처")
            self.ship_input.setVisible(True)
            self.ship_label.setVisible(True)
        else:
            self.company_input.setPlaceholderText("예: 변경 사유 또는 관련 회사")
            self.ship_input.setVisible(False)
            self.ship_label.setVisible(False)

        self.update_preview()

    def update_acetylene_box(self):
        is_acetylene = self.item_combo.currentText() == "아세틸렌"
        self.acetylene_numbers.setEnabled(is_acetylene)
        self.acetylene_hint.setVisible(is_acetylene)
        if is_acetylene:
            self.acetylene_numbers.setPlaceholderText("아세틸렌 용기번호를 한 줄에 하나씩 입력\n예:\nA-1023\nA-1024\nA-1025")
        else:
            self.acetylene_numbers.setPlaceholderText("아세틸렌 품목 선택 시 용기번호 입력")
            self.acetylene_numbers.clear()
        self.update_preview()

    def update_preview(self):
        mode = self.current_mode
        item = self.item_combo.currentText()
        location = self.location_combo.currentText()
        status = self.status_combo.currentText()
        to_location = self.to_location_combo.currentText()
        to_status = self.to_status_combo.currentText()
        qty = self.qty_spin.value()
        company = self.company_input.text().strip() or "-"
        ship = self.ship_input.text().strip() or "-"
        memo = self.memo.toPlainText().strip() or "-"
        cyl_numbers = [
            x.strip() for x in self.acetylene_numbers.toPlainText().splitlines()
            if x.strip()
        ]

        lines = [
            f"작업: {mode}",
            f"품목: {item} / 현재상태: {status} / 수량: {qty}병",
            f"현재 장소: {location}",
        ]

        if mode == "상태/장소 변경":
            lines.append(f"변경 후: {to_location} / {to_status}")

        if mode == "출고":
            lines.append(f"납품회사: {company}")
            lines.append(f"선명: {ship}")
        elif mode == "입고":
            lines.append(f"입고처/공급처: {company}")
        else:
            lines.append(f"관련 내용: {company}")

        if item == "아세틸렌":
            if cyl_numbers:
                lines.append(f"아세틸렌 용기번호: {', '.join(cyl_numbers)}")
                if len(cyl_numbers) != qty:
                    lines.append(f"주의: 수량은 {qty}병인데 용기번호는 {len(cyl_numbers)}개 입력됨")
            else:
                lines.append("아세틸렌 용기번호: 미입력")

        lines.append(f"메모: {memo}")
        self.preview_text.setText("\n".join(lines))



class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("가스병 재고관리 로그인")
        self.setMinimumSize(560, 520)
        self.setModal(True)
        self.apply_login_styles()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        outer = QFrame()
        outer.setObjectName("LoginOuter")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(34, 32, 34, 32)
        outer_layout.setSpacing(18)

        top = QHBoxLayout()
        logo = QLabel("▥")
        logo.setObjectName("LoginLogo")
        logo.setAlignment(Qt.AlignCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("가스병 재고관리")
        title.setObjectName("LoginTitle")
        sub = QLabel("GAS INVENTORY SYSTEM")
        sub.setObjectName("LoginSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)

        top.addWidget(logo)
        top.addSpacing(12)
        top.addLayout(title_box, 1)
        outer_layout.addLayout(top)

        card = QFrame()
        card.setObjectName("LoginCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 24, 26, 24)
        card_layout.setSpacing(16)

        card_title = QLabel("사용자 확인")
        card_title.setObjectName("LoginCardTitle")
        card_layout.addWidget(card_title)

        card_desc = QLabel("입고·출고 작업 기록에 남길 직책과 이름을 입력해주세요.")
        card_desc.setObjectName("LoginCardDesc")
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        role_group = QVBoxLayout()
        role_group.setSpacing(7)
        role_label = QLabel("직책")
        role_label.setObjectName("LoginInputLabel")
        self.role_input = QLineEdit()
        self.role_input.setObjectName("LoginInput")
        self.role_input.setPlaceholderText("예: 대표, 과장, 기사, 관리자")
        role_group.addWidget(role_label)
        role_group.addWidget(self.role_input)

        name_group = QVBoxLayout()
        name_group.setSpacing(7)
        name_label = QLabel("이름")
        name_label.setObjectName("LoginInputLabel")
        self.name_input = QLineEdit()
        self.name_input.setObjectName("LoginInput")
        self.name_input.setPlaceholderText("예: 한승수")
        name_group.addWidget(name_label)
        name_group.addWidget(self.name_input)

        card_layout.addLayout(role_group)
        card_layout.addLayout(name_group)

        hint = QLabel("직책을 먼저 입력하고, 이름까지 입력해야 프로그램을 사용할 수 있습니다.")
        hint.setObjectName("LoginHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.exit_btn = QPushButton("종료")
        self.exit_btn.setObjectName("LoginGhostButton")
        self.login_btn = QPushButton("프로그램 시작")
        self.login_btn.setObjectName("LoginPrimaryButton")
        self.exit_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setCursor(Qt.PointingHandCursor)

        self.exit_btn.clicked.connect(self.reject)
        self.login_btn.clicked.connect(self.try_login)

        btns.addWidget(self.exit_btn)
        btns.addWidget(self.login_btn)
        card_layout.addLayout(btns)

        outer_layout.addWidget(card)

        bottom = QLabel("로컬 저장 + 서버 연동 준비 버전")
        bottom.setObjectName("LoginBottom")
        bottom.setAlignment(Qt.AlignCenter)
        outer_layout.addWidget(bottom)

        root.addWidget(outer)

        self.role_input.returnPressed.connect(self.name_input.setFocus)
        self.name_input.returnPressed.connect(self.try_login)
        self.role_input.setFocus()

    def apply_login_styles(self):
        self.setStyleSheet("""
        QDialog {
            background: #f4f7fb;
        }

        #LoginOuter {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #eef4ff, stop:0.48 #f8fafc, stop:1 #ffffff);
        }

        #LoginLogo {
            min-width: 54px;
            min-height: 54px;
            border-radius: 16px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #3b82f6, stop:1 #6d5dfc);
            color: #ffffff;
            font-size: 31px;
            font-weight: 900;
        }

        #LoginTitle {
            color: #0f172a;
            font-size: 25px;
            font-weight: 900;
        }

        #LoginSub {
            color: #64748b;
            font-size: 11px;
            font-weight: 900;
            letter-spacing: 1.4px;
        }

        #LoginCard {
            background: #ffffff;
            border: 1px solid #dbe4ef;
            border-radius: 18px;
        }

        #LoginCardTitle {
            color: #0f172a;
            font-size: 22px;
            font-weight: 900;
        }

        #LoginCardDesc {
            color: #64748b;
            font-size: 13px;
            font-weight: 700;
            padding-bottom: 4px;
        }

        #LoginInputLabel {
            color: #334155;
            font-size: 13px;
            font-weight: 900;
        }

        #LoginInput {
            min-height: 44px;
            border-radius: 11px;
            border: 1px solid #dbe4ef;
            background: #f8fafc;
            color: #0f172a;
            padding: 0 14px;
            font-size: 15px;
            font-weight: 700;
            selection-background-color: #bfdbfe;
        }

        #LoginInput:hover {
            border: 1px solid #93c5fd;
            background: #ffffff;
        }

        #LoginInput:focus {
            border: 1px solid #4f6df5;
            background: #ffffff;
        }

        #LoginHint {
            color: #2563eb;
            background: #eef4ff;
            border: 1px solid #bfdbfe;
            border-radius: 10px;
            padding: 11px 13px;
            font-size: 12px;
            font-weight: 800;
        }

        #LoginGhostButton {
            min-height: 42px;
            border-radius: 10px;
            border: 1px solid #dbe4ef;
            background: #f8fafc;
            color: #334155;
            font-size: 14px;
            font-weight: 900;
        }

        #LoginGhostButton:hover {
            background: #eef4ff;
            border: 1px solid #bfdbfe;
        }

        #LoginPrimaryButton {
            min-height: 42px;
            border-radius: 10px;
            border: none;
            background: #4f6df5;
            color: #ffffff;
            font-size: 14px;
            font-weight: 900;
        }

        #LoginPrimaryButton:hover {
            background: #3f5ae0;
        }

        #LoginBottom {
            color: #94a3b8;
            font-size: 12px;
            font-weight: 800;
        }

        QMessageBox {
            background: #ffffff;
        }

        QMessageBox QLabel {
            color: #0f172a;
            font-size: 13px;
            font-weight: 700;
        }

        QMessageBox QPushButton {
            min-width: 78px;
            min-height: 30px;
            border-radius: 8px;
            border: none;
            background: #4f6df5;
            color: #ffffff;
            font-weight: 800;
        }
        """)

    def try_login(self):
        role = self.role_input.text().strip()
        name = self.name_input.text().strip()

        if not role:
            QMessageBox.warning(self, "입력 확인", "직책을 먼저 입력해주세요.")
            self.role_input.setFocus()
            return

        if not name:
            QMessageBox.warning(self, "입력 확인", "이름을 입력해주세요.")
            self.name_input.setFocus()
            return

        self.accept()

    def get_login_info(self):
        return self.role_input.text().strip(), self.name_input.text().strip()


class ServerSettingsDialog(QDialog):
    def __init__(self, current_url="", sync_count=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("서버 연동 설정")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("서버 연동 설정")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        desc = QLabel("현재는 서버 연동 준비 단계입니다. 서버 주소를 저장하고 연결 테스트를 할 수 있습니다.")
        desc.setObjectName("DialogDesc")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(12)

        self.server_url = QLineEdit()
        self.server_url.setPlaceholderText("예: https://gas-inventory-server.onrender.com")
        self.server_url.setText(current_url)

        self.sync_count_label = QLabel(f"{sync_count}건")
        self.sync_count_label.setObjectName("ServerStatusValue")

        form.addRow("서버 주소", self.server_url)
        form.addRow("동기화 대기", self.sync_count_label)
        layout.addLayout(form)

        guide = QFrame()
        guide.setObjectName("PreviewBox")
        guide_l = QVBoxLayout(guide)
        guide_l.setContentsMargins(14, 12, 14, 12)

        guide_title = QLabel("v0.2.3 서버 API 형식")
        guide_title.setObjectName("PreviewTitle")
        guide_text = QLabel(
            "GET  /health                       서버 상태 확인\n"
            "POST /api/v1/client/register       클라이언트/사용자 등록\n"
            "POST /api/v1/sync/push             로컬 변경내역 서버 전송\n"
            "GET  /api/v1/sync/pull             서버 최신 스냅샷/이력 가져오기"
        )
        guide_text.setObjectName("PreviewText")
        guide_text.setWordWrap(True)
        guide_l.addWidget(guide_title)
        guide_l.addWidget(guide_text)
        layout.addWidget(guide)

        btns = QHBoxLayout()
        test_btn = QPushButton("연결 테스트")
        test_btn.setObjectName("GhostButton")
        test_btn.clicked.connect(self.test_connection)

        sync_btn = QPushButton("대기목록 전송")
        sync_btn.setObjectName("PrimaryButton")
        sync_btn.clicked.connect(self.push_pending_from_parent)

        close_btn = QPushButton("취소")
        close_btn.setObjectName("GhostButton")
        save_btn = QPushButton("저장")
        save_btn.setObjectName("PrimaryButton")

        close_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)

        btns.addWidget(test_btn)
        btns.addWidget(sync_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def get_url(self):
        return self.server_url.text().strip().rstrip("/")


    def push_pending_from_parent(self):
        parent = self.parent()
        if parent is None or not hasattr(parent, "push_pending_sync_events"):
            QMessageBox.warning(self, "대기목록 전송", "메인 프로그램 연결을 찾을 수 없습니다.")
            return

        url = self.get_url()
        if url:
            parent.set_app_setting("server_url", url)

        ok, message = parent.push_pending_sync_events()
        if ok:
            self.sync_count_label.setText(f"{parent.get_pending_sync_count()}건")
            QMessageBox.information(self, "대기목록 전송", message)
        else:
            QMessageBox.warning(self, "대기목록 전송 실패", message)

    def test_connection(self):
        url = self.get_url()
        if not url:
            QMessageBox.warning(self, "연결 테스트", "서버 주소를 입력해주세요.")
            return

        test_url = url + "/health"
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "GasInventoryClient/0.2.3"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = resp.read(300).decode("utf-8", errors="ignore")
            QMessageBox.information(self, "연결 테스트", f"서버 응답 성공\n상태코드: {status}\n응답: {body[:200]}")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "연결 테스트 실패",
                "서버에 연결하지 못했습니다.\n\n"
                "아직 서버가 준비되지 않았으면 정상입니다.\n"
                f"확인 주소: {test_url}\n\n오류: {exc}"
            )


class ManageListDialog(QDialog):
    def __init__(self, title, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 460)
        self.values = list(values)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("DialogTitle")
        layout.addWidget(title_lbl)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("새 항목명 입력")
        add_btn = QPushButton("추가")
        add_btn.setObjectName("PrimaryButton")
        input_row.addWidget(self.input)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        edit_btn = QPushButton("선택 수정")
        edit_btn.setObjectName("GhostButton")
        del_btn = QPushButton("선택 삭제")
        del_btn.setObjectName("DangerButton")
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("PrimaryButton")
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        add_btn.clicked.connect(self.add_item)
        edit_btn.clicked.connect(self.edit_item)
        del_btn.clicked.connect(self.delete_item)
        close_btn.clicked.connect(self.accept)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        for value in self.values:
            self.list_widget.addItem(QListWidgetItem(value))

    def add_item(self):
        text = self.input.text().strip()
        if text and text not in self.values:
            self.values.append(text)
            self.input.clear()
            self.refresh()

    def edit_item(self):
        row = self.list_widget.currentRow()
        text = self.input.text().strip()
        if row >= 0 and text:
            self.values[row] = text
            self.input.clear()
            self.refresh()

    def delete_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.values.pop(row)
            self.refresh()


class MainWindow(QMainWindow):
    def __init__(self, user_role="", user_name=""):
        super().__init__()
        self.user_role = user_role or "사용자"
        self.user_name = user_name or "미입력"
        self.worker_name = f"{self.user_role} {self.user_name}"
        self.setWindowTitle(f"가스병 재고관리 v{APP_VERSION} - {self.worker_name}")
        self.resize(1500, 920)
        self.setMinimumSize(1200, 780)

        self.items = ["산소", "아세틸렌", "질소 180bar", "질소 200bar", "404", "407"]
        self.locations = ["현대케미칼", "예강창고"]
        self.rows = [
            InventoryRow("산소", "O₂", "현대케미칼", 10, 3, 1, 0),
            InventoryRow("산소", "O₂", "예강창고", 20, 5, 0, 0),
            InventoryRow("아세틸렌", "C₂H₂", "현대케미칼", 4, 2, 0, 1),
            InventoryRow("아세틸렌", "C₂H₂", "예강창고", 8, 1, 0, 0),
            InventoryRow("질소 180bar", "N₂ 180bar", "현대케미칼", 12, 3, 1, 0),
            InventoryRow("질소 180bar", "N₂ 180bar", "예강창고", 15, 6, 2, 0),
            InventoryRow("질소 200bar", "N₂ 200bar", "현대케미칼", 6, 4, 0, 0),
            InventoryRow("질소 200bar", "N₂ 200bar", "예강창고", 9, 2, 1, 0),
            InventoryRow("404", "R-404A", "현대케미칼", 7, 2, 0, 1),
            InventoryRow("404", "R-404A", "예강창고", 5, 1, 0, 0),
            InventoryRow("407", "R-407C", "현대케미칼", 6, 1, 0, 0),
            InventoryRow("407", "R-407C", "예강창고", 6, 0, 0, 0),
        ]

        self.acetylene_cylinders = [
            {"no": "A-1023", "status": "출고중", "location": "-", "last": "출고", "company": "현대글로비스", "ship": "HMM OCEAN", "date": "2026.06.24", "memo": "본선 납품"},
            {"no": "A-1024", "status": "보유중", "location": "현대케미칼", "last": "입고", "company": "충전소", "ship": "-", "date": "2026.06.23", "memo": "실병 입고"},
            {"no": "A-1025", "status": "공병", "location": "예강창고", "last": "회수", "company": "OO상사", "ship": "STAR LUCKY", "date": "2026.06.22", "memo": "회수 완료"},
            {"no": "A-1026", "status": "리페어", "location": "예강창고", "last": "리페어", "company": "내부", "ship": "-", "date": "2026.06.20", "memo": "밸브 점검"},
            {"no": "A-1027", "status": "보유중", "location": "현대케미칼", "last": "입고", "company": "충전소", "ship": "-", "date": "2026.06.18", "memo": "실병 입고"},
            {"no": "A-1028", "status": "출고중", "location": "-", "last": "출고", "company": "대양해운", "ship": "BLUE MARINE", "date": "2026.06.18", "memo": "선박 납품"},
        ]

        self.history_rows = [
            {"time": "2026.06.24 14:25", "work": "입고", "item": "산소", "status": "실병", "qty": "+5", "location": "현대케미칼", "company": "OO가스", "ship": "-", "cylinders": "-", "worker": "관리자", "memo": "실병 입고", "before_after": "실병 5 → 10"},
            {"time": "2026.06.24 14:20", "work": "출고", "item": "아세틸렌", "status": "실병", "qty": "-2", "location": "현대케미칼", "company": "현대글로비스", "ship": "HMM OCEAN", "cylinders": "A-1023, A-1028", "worker": "관리자", "memo": "본선 납품", "before_after": "실병 6 → 4 / A-1023, A-1028 출고중"},
            {"time": "2026.06.24 14:15", "work": "장소이동", "item": "404", "status": "실병", "qty": "3", "location": "현대케미칼 → 예강창고", "company": "내부", "ship": "-", "cylinders": "-", "worker": "관리자", "memo": "예강창고 보충", "before_after": "현대케미칼 -3 / 예강창고 +3"},
            {"time": "2026.06.24 14:10", "work": "폐기", "item": "아세틸렌", "status": "폐기", "qty": "-1", "location": "현대케미칼", "company": "내부", "ship": "-", "cylinders": "A-1019", "worker": "관리자", "memo": "용기 불량 폐기", "before_after": "폐기 +1 / A-1019 폐기"},
            {"time": "2026.06.24 14:05", "work": "입고", "item": "407", "status": "실병", "qty": "+4", "location": "예강창고", "company": "OO가스", "ship": "-", "cylinders": "-", "worker": "관리자", "memo": "냉매 입고", "before_after": "실병 2 → 6"},
            {"time": "2026.06.23 17:40", "work": "회수", "item": "아세틸렌", "status": "공병", "qty": "+1", "location": "예강창고", "company": "OO상사", "ship": "STAR LUCKY", "cylinders": "A-1025", "worker": "관리자", "memo": "선박 납품분 회수", "before_after": "A-1025 출고중 → 공병"},
            {"time": "2026.06.23 11:30", "work": "상태변경", "item": "질소 200bar", "status": "공병", "qty": "2", "location": "현대케미칼", "company": "내부", "ship": "-", "cylinders": "-", "worker": "관리자", "memo": "사용 완료", "before_after": "실병 -2 / 공병 +2"},
            {"time": "2026.06.22 09:10", "work": "취소처리", "item": "산소", "status": "실병", "qty": "+50 취소", "location": "예강창고", "company": "OO가스", "ship": "-", "cylinders": "-", "worker": "관리자", "memo": "수량 오입력 취소", "before_after": "입고 +50 기록 취소"},
        ]

        self.db_path = Path(__file__).with_name("gas_inventory_data.sqlite3")
        self.init_database()
        self.load_or_seed_database()

        self.root = QWidget()
        self.setCentralWidget(self.root)
        root_layout = QHBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = self.create_sidebar()
        self.content = self.create_content()

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.content, 1)

        self.apply_styles()

    def totals(self):
        full = sum(r.full for r in self.rows)
        empty = sum(r.empty for r in self.rows)
        repair = sum(r.repair for r in self.rows)
        disposal = sum(r.disposal for r in self.rows)
        return full + empty + repair + disposal, full, empty, repair, disposal

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    name TEXT PRIMARY KEY,
                    sort_order INTEGER NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS locations (
                    name TEXT PRIMARY KEY,
                    sort_order INTEGER NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    item TEXT NOT NULL,
                    item_sub TEXT NOT NULL,
                    location TEXT NOT NULL,
                    full INTEGER NOT NULL DEFAULT 0,
                    empty INTEGER NOT NULL DEFAULT 0,
                    repair INTEGER NOT NULL DEFAULT 0,
                    disposal INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (item, location)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS acetylene_cylinders (
                    no TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    location TEXT NOT NULL,
                    last TEXT NOT NULL,
                    company TEXT NOT NULL,
                    ship TEXT NOT NULL,
                    date TEXT NOT NULL,
                    memo TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS io_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL,
                    time TEXT NOT NULL,
                    work TEXT NOT NULL,
                    item TEXT NOT NULL,
                    status TEXT NOT NULL,
                    qty TEXT NOT NULL,
                    location TEXT NOT NULL,
                    company TEXT NOT NULL,
                    ship TEXT NOT NULL,
                    cylinders TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    memo TEXT NOT NULL,
                    before_after TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT NOT NULL DEFAULT '',
                    synced_at TEXT NOT NULL DEFAULT ''
                )
            """)
            cur.execute("PRAGMA table_info(sync_queue)")
            existing_cols = {row[1] for row in cur.fetchall()}
            if "synced_at" not in existing_cols:
                cur.execute("ALTER TABLE sync_queue ADD COLUMN synced_at TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def load_or_seed_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM inventory")
            inventory_count = cur.fetchone()[0]

        if inventory_count == 0:
            self.save_all_to_database()
        else:
            self.load_all_from_database()

    def load_all_from_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("SELECT name FROM items ORDER BY sort_order, name")
            self.items = [row["name"] for row in cur.fetchall()]

            cur.execute("SELECT name FROM locations ORDER BY sort_order, name")
            self.locations = [row["name"] for row in cur.fetchall()]

            cur.execute("""
                SELECT item, item_sub, location, full, empty, repair, disposal
                FROM inventory
                ORDER BY item, location
            """)
            self.rows = [
                InventoryRow(
                    row["item"], row["item_sub"], row["location"],
                    int(row["full"]), int(row["empty"]),
                    int(row["repair"]), int(row["disposal"])
                )
                for row in cur.fetchall()
            ]

            cur.execute("""
                SELECT no, status, location, last, company, ship, date, memo
                FROM acetylene_cylinders
                ORDER BY no
            """)
            self.acetylene_cylinders = [dict(row) for row in cur.fetchall()]

            cur.execute("""
                SELECT time, work, item, status, qty, location, company, ship,
                       cylinders, worker, memo, before_after
                FROM io_history
                ORDER BY sort_order
            """)
            self.history_rows = [dict(row) for row in cur.fetchall()]

        if not self.items:
            self.items = ["산소", "아세틸렌", "질소 180bar", "질소 200bar", "404", "407"]
        if not self.locations:
            self.locations = ["현대케미칼", "예강창고"]

    def save_all_to_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM items")
            cur.execute("DELETE FROM locations")
            cur.execute("DELETE FROM inventory")
            cur.execute("DELETE FROM acetylene_cylinders")
            cur.execute("DELETE FROM io_history")

            for idx, item in enumerate(self.items):
                cur.execute("INSERT INTO items (name, sort_order) VALUES (?, ?)", (item, idx))

            for idx, location in enumerate(self.locations):
                cur.execute("INSERT INTO locations (name, sort_order) VALUES (?, ?)", (location, idx))

            for row in self.rows:
                cur.execute("""
                    INSERT INTO inventory
                    (item, item_sub, location, full, empty, repair, disposal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    row.item, row.item_sub, row.location,
                    int(row.full), int(row.empty), int(row.repair), int(row.disposal)
                ))

            for cyl in self.acetylene_cylinders:
                cur.execute("""
                    INSERT OR REPLACE INTO acetylene_cylinders
                    (no, status, location, last, company, ship, date, memo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cyl.get("no", ""), cyl.get("status", ""), cyl.get("location", ""),
                    cyl.get("last", ""), cyl.get("company", ""), cyl.get("ship", ""),
                    cyl.get("date", ""), cyl.get("memo", "")
                ))

            for idx, row in enumerate(self.history_rows):
                cur.execute("""
                    INSERT INTO io_history
                    (sort_order, time, work, item, status, qty, location, company,
                     ship, cylinders, worker, memo, before_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    idx,
                    row.get("time", ""), row.get("work", ""), row.get("item", ""),
                    row.get("status", ""), row.get("qty", ""), row.get("location", ""),
                    row.get("company", ""), row.get("ship", ""), row.get("cylinders", ""),
                    row.get("worker", ""), row.get("memo", ""), row.get("before_after", "")
                ))

            conn.commit()


    def get_app_setting(self, key, default=""):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
                row = cur.fetchone()
                return row[0] if row else default
        except Exception:
            return default

    def set_app_setting(self, key, value):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()

    def get_pending_sync_count(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM sync_queue WHERE status = 'pending'")
                return int(cur.fetchone()[0])
        except Exception:
            return 0

    def enqueue_sync_event(self, event_type, payload):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO sync_queue (created_at, event_type, payload, status, last_error)
                    VALUES (?, ?, ?, 'pending', '')
                """, (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    event_type,
                    json.dumps(payload, ensure_ascii=False)
                ))
                conn.commit()
        except Exception as exc:
            print(f"[sync_queue] enqueue failed: {exc}")


    def get_client_id(self):
        client_id = self.get_app_setting("client_id", "")
        if client_id:
            return client_id

        raw = f"{self.db_path}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        client_id = "gas-client-" + str(abs(hash(raw)))
        self.set_app_setting("client_id", client_id)
        return client_id

    def get_pending_sync_events(self, limit=100):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, created_at, event_type, payload
                FROM sync_queue
                WHERE status = 'pending'
                ORDER BY id
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()

        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {"raw": row["payload"]}

            events.append({
                "local_id": row["id"],
                "created_at": row["created_at"],
                "event_type": row["event_type"],
                "payload": payload,
            })
        return events

    def mark_sync_events_sent(self, local_ids):
        if not local_ids:
            return

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in local_ids)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE sync_queue SET status = 'sent', synced_at = ?, last_error = '' WHERE id IN ({placeholders})",
                [now_text, *local_ids]
            )
            conn.commit()

    def mark_sync_events_failed(self, local_ids, error):
        if not local_ids:
            return

        placeholders = ",".join("?" for _ in local_ids)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE sync_queue SET last_error = ? WHERE id IN ({placeholders})",
                [str(error)[:500], *local_ids]
            )
            conn.commit()

    def build_push_payload(self):
        events = self.get_pending_sync_events(limit=100)
        return {
            "client": {
                "client_id": self.get_client_id(),
                "app_version": APP_VERSION,
                "platform": "windows-pyside6",
            },
            "user": {
                "role": self.user_role,
                "name": self.user_name,
                "worker": self.worker_name,
            },
            "events": events,
            "snapshot": self.prepare_full_sync_payload(),
        }

    def post_json_to_server(self, path, payload, timeout=10):
        server_url = self.get_app_setting("server_url", "").strip().rstrip("/")
        if not server_url:
            raise RuntimeError("서버 주소가 설정되어 있지 않습니다. 설정에서 서버 주소를 먼저 입력해주세요.")

        url = server_url + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": f"GasInventoryClient/{APP_VERSION}",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            try:
                return json.loads(body)
            except Exception:
                return {"ok": True, "raw": body}

    def push_pending_sync_events(self):
        events = self.get_pending_sync_events(limit=100)
        if not events:
            return True, "전송할 동기화 대기목록이 없습니다."

        local_ids = [event["local_id"] for event in events]
        payload = self.build_push_payload()
        try:
            response = self.post_json_to_server("/api/v1/sync/push", payload, timeout=12)
            if not response.get("ok", False):
                raise RuntimeError(response.get("error", "서버가 ok=false를 반환했습니다."))
            self.mark_sync_events_sent(local_ids)
            self.rebuild_pages_after_data_change()
            return True, f"{len(local_ids)}건 전송 완료\\n서버 리비전: {response.get('server_revision', '-')}"
        except Exception as exc:
            self.mark_sync_events_failed(local_ids, exc)
            return False, str(exc)

    def register_client_to_server(self):
        payload = {
            "client": {
                "client_id": self.get_client_id(),
                "app_version": APP_VERSION,
                "platform": "windows-pyside6",
            },
            "user": {
                "role": self.user_role,
                "name": self.user_name,
                "worker": self.worker_name,
            },
        }
        return self.post_json_to_server("/api/v1/client/register", payload, timeout=8)

    def prepare_full_sync_payload(self):
        return {
            "version": APP_VERSION,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": self.get_client_id(),
            "user": {
                "role": self.user_role,
                "name": self.user_name,
                "worker": self.worker_name,
            },
            "items": self.items,
            "locations": self.locations,
            "inventory": [
                {
                    "item": row.item,
                    "item_sub": row.item_sub,
                    "location": row.location,
                    "full": row.full,
                    "empty": row.empty,
                    "repair": row.repair,
                    "disposal": row.disposal,
                }
                for row in self.rows
            ],
            "acetylene_cylinders": self.acetylene_cylinders,
            "history_rows": self.history_rows,
        }

    def open_server_settings_dialog(self):
        current_url = self.get_app_setting("server_url", "")
        dlg = ServerSettingsDialog(current_url, self.get_pending_sync_count(), self)
        if dlg.exec():
            self.set_app_setting("server_url", dlg.get_url())
            QMessageBox.information(
                self,
                "서버 설정 저장",
                "서버 주소가 저장되었습니다.\n"
                "서버 API 형식은 v0.2.3 기준으로 확정되었습니다. 대기목록 전송 버튼으로 서버 전송을 테스트할 수 있습니다."
            )

    def create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(250)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 24, 18, 18)
        layout.setSpacing(10)

        logo_row = QHBoxLayout()
        logo = QLabel("▥")
        logo.setObjectName("LogoIcon")
        logo.setAlignment(Qt.AlignCenter)
        title_box = QVBoxLayout()
        title = QLabel("가스병 재고관리")
        title.setObjectName("LogoTitle")
        sub = QLabel("GAS INVENTORY SYSTEM")
        sub.setObjectName("LogoSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        logo_row.addWidget(logo)
        logo_row.addLayout(title_box, 1)
        layout.addLayout(logo_row)
        layout.addSpacing(18)

        self.nav_buttons = {}
        buttons = [
            ("dashboard", "⌂   대시보드", True),
            ("stock", "▣   재고 현황", False),
            ("io", "⇄   입고 / 출고", False),
            ("history", "↺   입출고 내역", False),
            ("items", "▤   품목 관리", False),
            ("locations", "⌖   장소 관리", False),
            ("stats", "▥   통계 / 분석", False),
            ("settings", "⚙   설정", False),
        ]

        for key, text, active in buttons:
            btn = SideButton(text, active)
            self.nav_buttons[key] = btn
            if key == "dashboard":
                btn.clicked.connect(lambda checked=False: self.switch_page("dashboard"))
            elif key == "stock":
                btn.clicked.connect(lambda checked=False: self.switch_page("stock"))
            elif key == "io":
                btn.clicked.connect(self.open_stock_dialog)
            elif key == "items":
                btn.clicked.connect(self.open_item_dialog)
            elif key == "locations":
                btn.clicked.connect(self.open_location_dialog)
            elif key == "history":
                btn.clicked.connect(lambda checked=False: self.switch_page("history"))
            elif key == "stats":
                btn.clicked.connect(lambda checked=False: QMessageBox.information(self, "통계 / 분석", "다음 버전에서 월별 입출고 통계를 구성할 수 있습니다."))
            elif key == "settings":
                btn.clicked.connect(self.open_server_settings_dialog)
            layout.addWidget(btn)

        layout.addStretch()

        help_box = QFrame()
        help_box.setObjectName("HelpBox")
        help_layout = QVBoxLayout(help_box)
        help_layout.setContentsMargins(16, 16, 16, 16)
        h1 = QLabel("도움이 필요하세요?")
        h1.setObjectName("HelpTitle")
        h2 = QLabel("프로그램 사용 중 문제가 발생하면\n관리자에게 문의해주세요.")
        h2.setObjectName("HelpSub")
        hb = QPushButton("문의하기")
        hb.setObjectName("HelpButton")
        help_layout.addWidget(h1)
        help_layout.addWidget(h2)
        help_layout.addWidget(hb)
        layout.addWidget(help_box)

        footer = QLabel("© 2026 GAS Inventory System")
        footer.setObjectName("Footer")
        layout.addWidget(footer)

        return sidebar

    def create_content(self):
        content = QFrame()
        content.setObjectName("Content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 0, 24, 18)
        layout.setSpacing(16)

        topbar = self.create_topbar()
        layout.addWidget(topbar)

        self.stack = QStackedWidget()
        self.dashboard_page = self.create_dashboard_page()
        self.stock_page = self.create_stock_status_page()
        self.history_page = self.create_history_page()

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.stock_page)
        self.stack.addWidget(self.history_page)
        layout.addWidget(self.stack, 1)

        return content

    def switch_page(self, page):
        if not hasattr(self, "stack"):
            return

        if page == "dashboard":
            target_index = 0
        elif page == "stock":
            target_index = 1
        elif page == "history":
            target_index = 2
        else:
            target_index = 0
        self.stack.setCurrentIndex(target_index)

        for key, btn in self.nav_buttons.items():
            active = key == page
            btn.setChecked(active)
            btn.setObjectName("SideButtonActive" if active else "SideButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def create_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        cards = self.create_cards()
        layout.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self.create_inventory_panel(), 3)
        left.addWidget(self.create_history_panel(), 1)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self.create_quick_panel())
        right.addWidget(self.create_chart_panel())
        right.addWidget(self.create_notice_panel())

        body.addLayout(left, 1)
        body.addLayout(right, 0)
        layout.addLayout(body, 1)
        return page

    def create_stock_status_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header_panel = QFrame()
        header_panel.setObjectName("Panel")
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("재고 현황")
        title.setObjectName("PageTitle")
        sub = QLabel("장소별 재고, 품목별 상세 수량, 아세틸렌 용기번호를 한 화면에서 확인합니다.")
        sub.setObjectName("PageSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        title_row.addLayout(title_box, 1)

        refresh_btn = QPushButton("새로고침")
        refresh_btn.setObjectName("GhostButton")
        export_btn = QPushButton("엑셀 내보내기")
        export_btn.setObjectName("PrimaryButton")
        title_row.addWidget(refresh_btn)
        title_row.addWidget(export_btn)
        header_layout.addLayout(title_row)

        filters = QHBoxLayout()
        self.stock_location_filter = QComboBox()
        self.stock_location_filter.addItems(["전체 장소"] + self.locations)
        self.stock_item_filter = QComboBox()
        self.stock_item_filter.addItems(["전체 품목"] + self.items)
        self.stock_status_filter = QComboBox()
        self.stock_status_filter.addItems(["전체 상태", "실병", "공병", "리페어", "폐기", "출고중", "보유중"])
        self.stock_search = QLineEdit()
        self.stock_search.setPlaceholderText("품목명 / 용기번호 / 납품회사 / 선명 검색...")

        for widget in [self.stock_location_filter, self.stock_item_filter, self.stock_status_filter, self.stock_search]:
            widget.setObjectName("Filter")
            filters.addWidget(widget)

        search_btn = QPushButton("검색")
        search_btn.setObjectName("PrimaryButton")
        filters.addWidget(search_btn)
        header_layout.addLayout(filters)
        layout.addWidget(header_panel)

        top_body = QHBoxLayout()
        top_body.setSpacing(14)
        for location in self.locations:
            top_body.addWidget(self.create_stock_location_summary_card(location), 1)
        top_body.addWidget(self.create_warning_stock_panel(), 1)
        layout.addLayout(top_body)

        tables = QHBoxLayout()
        tables.setSpacing(14)

        detail_panel = self.create_stock_detail_table_panel()
        acetylene_panel = self.create_acetylene_table_panel()

        tables.addWidget(detail_panel, 3)
        tables.addWidget(acetylene_panel, 2)
        layout.addLayout(tables, 1)

        return page

    def create_stock_location_summary_card(self, location):
        rows = [r for r in self.rows if r.location == location]
        full = sum(r.full for r in rows)
        empty = sum(r.empty for r in rows)
        repair = sum(r.repair for r in rows)
        disposal = sum(r.disposal for r in rows)
        total = full + empty + repair + disposal

        panel = QFrame()
        panel.setObjectName("StockSummaryCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        t = QLabel(location)
        t.setObjectName("LocationTitle")
        badge = QLabel(f"{total} 병")
        badge.setObjectName("LocationBadge")
        badge.setAlignment(Qt.AlignCenter)
        top.addWidget(t)
        top.addStretch()
        top.addWidget(badge)
        layout.addLayout(top)

        sub = QLabel(f"실병 {full} · 공병 {empty} · 리페어 {repair} · 폐기 {disposal}")
        sub.setObjectName("LocationSub")
        layout.addWidget(sub)

        bars = QVBoxLayout()
        for name, value, color in [
            ("실병", full, "#059669"),
            ("공병", empty, "#f97316"),
            ("리페어", repair, "#8b5cf6"),
            ("폐기", disposal, "#ef4444"),
        ]:
            row = QHBoxLayout()
            label = QLabel(name)
            label.setObjectName("SmallMetricLabel")
            val = QLabel(f"{value} 병")
            val.setObjectName("SmallMetricValue")
            val.setStyleSheet(f"color: {color};")
            row.addWidget(label)
            row.addStretch()
            row.addWidget(val)
            bars.addLayout(row)
        layout.addLayout(bars)
        return panel

    def create_warning_stock_panel(self):
        panel = QFrame()
        panel.setObjectName("WarningPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        title = QLabel("주의 재고")
        title.setObjectName("WarningTitle")
        layout.addWidget(title)

        warnings = [
            ("아세틸렌 현대케미칼 실병 4병", "낮음"),
            ("질소 200bar 공병 6병", "회수 필요"),
            ("아세틸렌 A-1026 리페어", "점검중"),
        ]
        for text, tag in warnings:
            row = QFrame()
            row.setObjectName("WarningRow")
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(10, 8, 10, 8)
            msg = QLabel(text)
            msg.setObjectName("WarningText")
            badge = QLabel(tag)
            badge.setObjectName("WarningBadge")
            badge.setAlignment(Qt.AlignCenter)
            row_l.addWidget(msg, 1)
            row_l.addWidget(badge)
            layout.addWidget(row)

        layout.addStretch()
        return panel

    def create_stock_detail_table_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("품목별 상세 재고")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        hint = QLabel("수량 기준 관리")
        hint.setObjectName("TableHint")
        title_row.addWidget(hint)
        layout.addLayout(title_row)

        table = QTableWidget()
        table.setObjectName("InventoryTable")
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["품목", "장소", "실병", "공병", "리페어", "폐기", "합계", "마지막 변경"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 8):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)

        table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            total = row.full + row.empty + row.repair + row.disposal
            values = [row.item, row.location, row.full, row.empty, row.repair, row.disposal, total, "2026.06.24 14:25"]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                if c == 2:
                    item.setForeground(QColor("#059669"))
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif c == 3:
                    item.setForeground(QColor("#f97316"))
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif c == 4:
                    item.setForeground(QColor("#8b5cf6"))
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif c == 5:
                    item.setForeground(QColor("#ef4444"))
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                table.setItem(r, c, item)
            table.setRowHeight(r, 42)

        layout.addWidget(table, 1)
        return panel

    def create_acetylene_table_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("아세틸렌 용기번호 현황")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        add_btn = QPushButton("+ 번호 등록")
        add_btn.setObjectName("GhostButton")
        add_btn.clicked.connect(lambda: QMessageBox.information(self, "번호 등록", "v0.1.5에서 아세틸렌 번호 등록 기능을 연결하면 됩니다."))
        title_row.addWidget(add_btn)
        layout.addLayout(title_row)

        table = QTableWidget()
        table.setObjectName("InventoryTable")
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["용기번호", "상태", "현재위치", "최근작업", "납품회사", "선명", "일자", "메모"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)

        table.setRowCount(len(self.acetylene_cylinders))
        for r, cyl in enumerate(self.acetylene_cylinders):
            values = [cyl["no"], cyl["status"], cyl["location"], cyl["last"], cyl["company"], cyl["ship"], cyl["date"], cyl["memo"]]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    item.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                if c == 1:
                    if value == "출고중":
                        item.setForeground(QColor("#2563eb"))
                    elif value == "보유중":
                        item.setForeground(QColor("#059669"))
                    elif value == "공병":
                        item.setForeground(QColor("#f97316"))
                    elif value == "리페어":
                        item.setForeground(QColor("#8b5cf6"))
                    elif value == "폐기":
                        item.setForeground(QColor("#ef4444"))
                    item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                table.setItem(r, c, item)
            table.setRowHeight(r, 38)

        layout.addWidget(table, 1)
        return panel


    def create_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header_panel = QFrame()
        header_panel.setObjectName("Panel")
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("입출고 내역")
        title.setObjectName("PageTitle")
        sub = QLabel("입고, 출고, 회수, 상태변경, 장소이동, 취소처리 이력을 추적합니다.")
        sub.setObjectName("PageSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        title_row.addLayout(title_box, 1)

        cancel_btn = QPushButton("선택 내역 취소처리")
        cancel_btn.setObjectName("DangerOutlineButton")
        cancel_btn.clicked.connect(self.show_cancel_history_message)
        export_btn = QPushButton("엑셀 내보내기")
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(lambda: QMessageBox.information(self, "엑셀 내보내기", "v0.1.6 이후 실제 입출고내역 저장 기능과 함께 연결하면 됩니다."))
        title_row.addWidget(cancel_btn)
        title_row.addWidget(export_btn)
        header_layout.addLayout(title_row)

        filters = QHBoxLayout()
        self.history_period_filter = QComboBox()
        self.history_period_filter.addItems(["이번 달", "오늘", "이번 주", "지난 달", "전체 기간"])
        self.history_work_filter = QComboBox()
        self.history_work_filter.addItems(["전체 작업", "입고", "출고", "회수", "상태변경", "장소이동", "장소/상태변경", "폐기", "취소처리"])
        self.history_item_filter = QComboBox()
        self.history_item_filter.addItems(["전체 품목"] + self.items)
        self.history_location_filter = QComboBox()
        self.history_location_filter.addItems(["전체 장소"] + self.locations)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("회사명 / 선명 / 용기번호 / 메모 검색...")
        self.setup_history_search_autocomplete()

        for widget in [
            self.history_period_filter, self.history_work_filter, self.history_item_filter,
            self.history_location_filter, self.history_search
        ]:
            widget.setObjectName("Filter")
            filters.addWidget(widget)

        search_btn = QPushButton("검색")
        search_btn.setObjectName("PrimaryButton")
        search_btn.clicked.connect(self.highlight_io_search_matches)
        self.history_search.textChanged.connect(self.highlight_io_search_matches)
        filters.addWidget(search_btn)
        header_layout.addLayout(filters)
        layout.addWidget(header_panel)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(14)
        summary_row.addWidget(self.create_history_summary_card("전체 작업", str(len(self.history_rows)), "이번 달 기록", "#64748b"), 1)
        summary_row.addWidget(self.create_history_summary_card("출고", str(self.count_history_work("출고")), "선박 납품 포함", "#2563eb"), 1)
        summary_row.addWidget(self.create_history_summary_card("아세틸렌 번호 이력", str(self.count_acetylene_history()), "용기번호 포함 기록", "#8b5cf6"), 1)
        summary_row.addWidget(self.create_history_summary_card("취소처리", str(self.count_history_work("취소처리")), "오입력 보정 기록", "#ef4444"), 1)
        layout.addLayout(summary_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        detail_panel = self.create_history_detail_panel()
        table_panel = self.create_history_table_panel()
        body.addWidget(table_panel, 3)
        body.addWidget(detail_panel, 1)
        layout.addLayout(body, 1)
        self.update_history_detail_from_selection()

        return page

    def count_history_work(self, work):
        return sum(1 for r in self.history_rows if r["work"] == work)

    def count_acetylene_history(self):
        return sum(1 for r in self.history_rows if r["item"] == "아세틸렌" or r["cylinders"] != "-")


    def setup_history_search_autocomplete(self):
        words = set()
        for row in self.history_rows:
            for key in ["company", "ship", "cylinders", "memo", "item", "location"]:
                value = str(row.get(key, "")).strip()
                if not value or value == "-":
                    continue
                # 전체 문구
                words.add(value)
                # 쉼표로 나뉜 용기번호
                for part in value.replace("→", " ").replace("/", " ").replace(",", " ").split():
                    cleaned = part.strip()
                    if cleaned and cleaned != "-":
                        words.add(cleaned)

        completer = QCompleter(sorted(words), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.history_search.setCompleter(completer)

    def highlight_io_search_matches(self):
        if not hasattr(self, "history_table"):
            return

        keyword = self.history_search.text().strip().lower()
        match_rows = []

        normal_bg = QColor("#ffffff")
        match_bg = QColor("#fff7cc")
        selected_bg = QColor("#dbeafe")

        keys = ["time", "work", "item", "status", "qty", "location", "company", "ship", "cylinders", "worker", "memo"]

        for r, row in enumerate(self.history_rows):
            haystack = " ".join(str(row.get(k, "")) for k in keys).lower()
            matched = bool(keyword) and keyword in haystack
            if matched:
                match_rows.append(r)

            for c in range(self.history_table.columnCount()):
                item = self.history_table.item(r, c)
                if item is None:
                    continue
                if matched:
                    item.setBackground(match_bg)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                else:
                    item.setBackground(normal_bg)
                    # 색상/굵기는 populate에서 다시 잡는 대신 검색 해제 시 최소한의 원상복구
                    if keys[c] not in ["work", "qty", "item"]:
                        font = item.font()
                        font.setBold(False)
                        item.setFont(font)

        if match_rows:
            first = match_rows[0]
            self.history_table.selectRow(first)
            self.history_table.scrollToItem(self.history_table.item(first, 0), QTableWidget.PositionAtCenter)
            # 선택행은 검색 강조보다 조금 더 강하게 보이도록 한 번 더 칠함
            for c in range(self.history_table.columnCount()):
                item = self.history_table.item(first, c)
                if item:
                    item.setBackground(selected_bg)
            self.update_history_detail_from_selection()
        elif keyword:
            self.history_detail_badge.setText("검색 결과 없음")
            self.history_detail_badge.setStyleSheet("background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; border-radius: 15px;")
            self.history_detail_text.setText("검색어와 일치하는 입출고 내역이 없습니다.\\n회사명, 선명, 용기번호 일부만 입력해도 검색할 수 있습니다.")
            self.history_before_after_text.setText("-")
        else:
            if self.history_rows:
                self.history_table.selectRow(0)
                self.update_history_detail_from_selection()

    def create_history_summary_card(self, title, value, subtitle, color):
        card = QFrame()
        card.setObjectName("HistorySummaryCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)

        texts = QVBoxLayout()
        t = QLabel(title)
        t.setObjectName("CardTitle")
        t.setStyleSheet(f"color: {color};")
        v = QLabel(value)
        v.setObjectName("HistorySummaryValue")
        s = QLabel(subtitle)
        s.setObjectName("CardSub")
        texts.addWidget(t)
        texts.addWidget(v)
        texts.addWidget(s)

        icon = QLabel("●")
        icon.setObjectName("HistorySummaryIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"color: {color}; background: {color}18; border-radius: 17px;")

        layout.addLayout(texts, 1)
        layout.addWidget(icon)
        return card

    def create_history_table_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("전체 입출고 내역")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        hint = QLabel("선택하면 오른쪽에 상세 표시")
        hint.setObjectName("TableHint")
        title_row.addWidget(hint)
        layout.addLayout(title_row)

        self.history_table = QTableWidget()
        self.history_table.setObjectName("InventoryTable")
        self.history_table.setColumnCount(11)
        self.history_table.setHorizontalHeaderLabels([
            "일시", "작업", "품목", "상태", "수량", "장소", "회사", "선명", "용기번호", "작업자", "메모"
        ])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)

        self.populate_history_table()
        self.history_table.itemSelectionChanged.connect(self.update_history_detail_from_selection)
        layout.addWidget(self.history_table, 1)
        return panel

    def populate_history_table(self):
        self.history_table.setRowCount(len(self.history_rows))
        keys = ["time", "work", "item", "status", "qty", "location", "company", "ship", "cylinders", "worker", "memo"]

        for r, row in enumerate(self.history_rows):
            for c, key in enumerate(keys):
                value = row[key]
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                if c in [5, 6, 7, 8, 10]:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if key == "work":
                    color = self.history_work_color(value)
                    item.setForeground(QColor(color))
                    item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                if key == "qty":
                    if str(value).startswith("+"):
                        item.setForeground(QColor("#059669"))
                    elif str(value).startswith("-"):
                        item.setForeground(QColor("#ef4444"))
                    item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                if key == "item" and value == "아세틸렌":
                    item.setForeground(QColor("#8b5cf6"))
                    item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                self.history_table.setItem(r, c, item)
            self.history_table.setRowHeight(r, 38)

        if self.history_rows:
            self.history_table.selectRow(0)

    def history_work_color(self, work):
        return {
            "입고": "#059669",
            "출고": "#2563eb",
            "회수": "#f97316",
            "상태변경": "#8b5cf6",
            "장소이동": "#0f766e",
            "장소/상태변경": "#0f766e",
            "폐기": "#ef4444",
            "취소처리": "#dc2626",
        }.get(work, "#334155")

    def create_history_detail_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("선택 입출고 내역 상세")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.history_detail_badge = QLabel("작업")
        self.history_detail_badge.setObjectName("DetailBadge")
        self.history_detail_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.history_detail_badge)

        self.history_detail_text = QLabel("")
        self.history_detail_text.setObjectName("DetailText")
        self.history_detail_text.setWordWrap(True)
        layout.addWidget(self.history_detail_text)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(divider)

        self.history_before_after_title = QLabel("재고 변화")
        self.history_before_after_title.setObjectName("DetailSectionTitle")
        layout.addWidget(self.history_before_after_title)

        self.history_before_after_text = QLabel("")
        self.history_before_after_text.setObjectName("BeforeAfterBox")
        self.history_before_after_text.setWordWrap(True)
        layout.addWidget(self.history_before_after_text)

        edit_btn = QPushButton("선택 입출고 내역 수정")
        edit_btn.setObjectName("GhostButton")
        edit_btn.clicked.connect(lambda: QMessageBox.information(self, "선택 입출고 내역 수정", "실제 저장 기능 연결 후 수정 기능을 붙이면 됩니다."))
        cancel_btn = QPushButton("취소처리 기록 추가")
        cancel_btn.setObjectName("DangerOutlineButton")
        cancel_btn.clicked.connect(self.show_cancel_history_message)
        excel_btn = QPushButton("이 입출고 내역만 출력")
        excel_btn.setObjectName("PrimaryButton")
        excel_btn.clicked.connect(lambda: QMessageBox.information(self, "출력", "이 입출고 내역만 엑셀/PDF로 출력하는 기능은 다음 단계에서 연결 가능합니다."))
        layout.addWidget(edit_btn)
        layout.addWidget(cancel_btn)
        layout.addWidget(excel_btn)

        layout.addStretch()
        return panel

    def update_history_detail_from_selection(self):
        if not hasattr(self, "history_table"):
            return
        row_index = self.history_table.currentRow()
        if row_index < 0 or row_index >= len(self.history_rows):
            return

        row = self.history_rows[row_index]
        color = self.history_work_color(row["work"])
        self.history_detail_badge.setText(row["work"])
        self.history_detail_badge.setStyleSheet(f"background: {color}18; color: {color}; border: 1px solid {color}33; border-radius: 15px;")

        detail = [
            f"일시: {row['time']}",
            f"품목: {row['item']} / 상태: {row['status']} / 수량: {row['qty']}",
            f"장소: {row['location']}",
            f"회사: {row['company']}",
            f"선명: {row['ship']}",
            f"용기번호: {row['cylinders']}",
            f"작업자: {row['worker']}",
            f"메모: {row['memo']}",
        ]
        self.history_detail_text.setText("\\n".join(detail))
        self.history_before_after_text.setText(row["before_after"])

    def show_cancel_history_message(self):
        QMessageBox.information(
            self,
            "취소처리 안내",
            "실제 운영에서는 기존 기록을 삭제하지 않고, 반대 기록을 새로 추가하는 방식으로 처리하는 것이 안전합니다.\\n\\n"
            "예: 잘못된 출고 기록 → 출고취소 기록 추가 → 올바른 출고 재입력"
        )

    def create_topbar(self):
        topbar = QFrame()
        topbar.setObjectName("Topbar")
        topbar.setFixedHeight(70)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addStretch()

        now = datetime.now().strftime("%Y.%m.%d (%a)  %H:%M")
        date = QLabel(now)
        date.setObjectName("TopText")
        bell = QLabel("🔔")
        bell.setObjectName("Bell")
        admin = QLabel(f"{self.user_role}\n{self.user_name}")
        admin.setObjectName("AdminText")
        avatar = QLabel("●")
        avatar.setObjectName("Avatar")
        avatar.setAlignment(Qt.AlignCenter)

        sync = QLabel(f"동기화 대기 {self.get_pending_sync_count()}건")
        sync.setObjectName("SyncText")

        layout.addWidget(sync)
        layout.addSpacing(16)
        layout.addWidget(date)
        layout.addSpacing(16)
        layout.addWidget(bell)
        layout.addSpacing(16)
        layout.addWidget(admin)
        layout.addWidget(avatar)

        return topbar

    def create_cards(self):
        total, full, empty, repair, disposal = self.totals()
        cards = QHBoxLayout()
        cards.setSpacing(18)
        card_data = [
            ("전체 병 수", f"{total} 병", "전체 재고 합계", "#64748b", "▥"),
            ("실병", f"{full} 병", "사용 가능한 병", "#059669", "▥"),
            ("공병", f"{empty} 병", "충전/재사용 필요", "#f97316", "▥"),
            ("리페어", f"{repair} 병", "수리 중인 병", "#8b5cf6", "🔧"),
            ("폐기", f"{disposal} 병", "폐기 처리된 병", "#ef4444", "🗑"),
        ]
        for data in card_data:
            cards.addWidget(Card(*data))
        return cards

    def create_inventory_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("현재 재고 현황  ⓘ")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch()

        self.item_filter = QComboBox()
        self.item_filter.addItems(["전체 품목"] + self.items)
        self.search = QLineEdit()
        self.search.setPlaceholderText("품목 검색...")
        self.search.setFixedWidth(180)

        for widget in [self.item_filter, self.search]:
            widget.setObjectName("Filter")
            header.addWidget(widget)

        add_btn = QPushButton("+  입고 / 출고")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.open_stock_dialog)
        header.addWidget(add_btn)

        layout.addLayout(header)

        # 장소별 재고 구역
        location_grid = QHBoxLayout()
        location_grid.setSpacing(14)

        self.location_tables = {}
        for location in self.locations:
            section = self.create_location_inventory_section(location)
            location_grid.addWidget(section, 1)

        layout.addLayout(location_grid, 1)

        return panel

    def create_location_inventory_section(self, location):
        section = QFrame()
        section.setObjectName("LocationSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(14, 12, 14, 14)
        section_layout.setSpacing(10)

        rows = [r for r in self.rows if r.location == location]
        full = sum(r.full for r in rows)
        empty = sum(r.empty for r in rows)
        repair = sum(r.repair for r in rows)
        disposal = sum(r.disposal for r in rows)
        total = full + empty + repair + disposal

        top = QHBoxLayout()
        left = QVBoxLayout()
        loc_title = QLabel(location)
        loc_title.setObjectName("LocationTitle")
        loc_sub = QLabel(f"전체 {total}병 · 실병 {full} · 공병 {empty} · 리페어 {repair} · 폐기 {disposal}")
        loc_sub.setObjectName("LocationSub")
        left.addWidget(loc_title)
        left.addWidget(loc_sub)
        top.addLayout(left, 1)

        badge = QLabel(f"{total} 병")
        badge.setObjectName("LocationBadge")
        badge.setAlignment(Qt.AlignCenter)
        top.addWidget(badge)
        section_layout.addLayout(top)

        mini_cards = QHBoxLayout()
        mini_cards.setSpacing(8)
        for name, value, color in [
            ("실병", full, "#059669"),
            ("공병", empty, "#f97316"),
            ("리페어", repair, "#8b5cf6"),
            ("폐기", disposal, "#ef4444"),
        ]:
            mini = QFrame()
            mini.setObjectName("MiniStatusCard")
            mini_l = QVBoxLayout(mini)
            mini_l.setContentsMargins(10, 8, 10, 8)
            n = QLabel(name)
            n.setObjectName("MiniStatusName")
            n.setStyleSheet(f"color: {color};")
            v = QLabel(f"{value}")
            v.setObjectName("MiniStatusValue")
            v.setStyleSheet(f"color: {color};")
            mini_l.addWidget(n)
            mini_l.addWidget(v)
            mini_cards.addWidget(mini)
        section_layout.addLayout(mini_cards)

        table = QTableWidget()
        table.setObjectName("InventoryTable")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["품목", "실병", "공병", "리페어", "폐기", "합계"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.populate_location_table(table, rows)
        self.location_tables[location] = table
        section_layout.addWidget(table, 1)

        return section

    def populate_location_table(self, table, rows):
        table.setRowCount(len(rows) + 1)
        for row_idx, row in enumerate(rows):
            total = row.full + row.empty + row.repair + row.disposal
            item_text = f"{row.item}\n{row.item_sub}"
            values = [item_text, row.full, row.empty, row.repair, row.disposal, total]

            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignCenter)
                if col == 0:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                if col == 1:
                    cell.setForeground(QColor("#059669"))
                    cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif col == 2:
                    cell.setForeground(QColor("#f97316"))
                    cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif col == 3:
                    cell.setForeground(QColor("#8b5cf6"))
                    cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                elif col == 4:
                    cell.setForeground(QColor("#ef4444"))
                    cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
                table.setItem(row_idx, col, cell)
            table.setRowHeight(row_idx, 48)

        full = sum(r.full for r in rows)
        empty = sum(r.empty for r in rows)
        repair = sum(r.repair for r in rows)
        disposal = sum(r.disposal for r in rows)
        total = full + empty + repair + disposal
        last = len(rows)
        summary = ["합계", full, empty, repair, disposal, total]
        for col, value in enumerate(summary):
            cell = QTableWidgetItem(str(value))
            cell.setTextAlignment(Qt.AlignCenter)
            cell.setBackground(QColor("#f8fafc"))
            cell.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
            if col == 0:
                cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if col == 1:
                cell.setForeground(QColor("#059669"))
            elif col == 2:
                cell.setForeground(QColor("#f97316"))
            elif col == 3:
                cell.setForeground(QColor("#8b5cf6"))
            elif col == 4:
                cell.setForeground(QColor("#ef4444"))
            table.setItem(last, col, cell)
        table.setRowHeight(last, 42)

    def create_quick_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("빠른 작업")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        quicks = [
            ("입고 / 출고", "납품회사, 선명, 용기번호 기록", "#3b82f6"),
            ("품목 관리", "품목 추가, 수정, 삭제", "#f97316"),
            ("장소 관리", "장소 추가, 수정, 삭제", "#8b5cf6"),
            ("입출고 내역", "전체 입출고 내역 확인", "#ef4444"),
        ]

        for name, sub, color in quicks:
            btn = QPushButton(f"{name}\n{sub}      ›")
            btn.setObjectName("QuickButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(58)
            if name == "입고 / 출고":
                btn.clicked.connect(self.open_stock_dialog)
            elif name == "품목 관리":
                btn.clicked.connect(self.open_item_dialog)
            elif name == "장소 관리":
                btn.clicked.connect(self.open_location_dialog)
            else:
                btn.clicked.connect(lambda: QMessageBox.information(self, "입출고 내역", "v0.1에서는 화면 시안만 제공됩니다."))
            layout.addWidget(btn)

        return panel

    def create_chart_panel(self):
        total, full, empty, repair, disposal = self.totals()

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("재고 현황 차트")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        chart = PieChartWidget(
            [full, empty, repair, disposal],
            ["실병", "공병", "리페어", "폐기"],
            ["#10b981", "#fb923c", "#8b5cf6", "#ef4444"]
        )
        layout.addWidget(chart)
        return panel

    def create_notice_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("공지사항")
        title.setObjectName("PanelTitle")
        more = QLabel("전체 보기")
        more.setObjectName("More")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(more)
        layout.addLayout(title_row)

        notices = [
            ("5월 정기 점검 안내", "2026.05.15"),
            ("재고 관리 수칙 업데이트", "2026.05.10"),
            ("시스템 점검 안내", "2026.05.08"),
        ]

        for text, date in notices:
            row = QLabel(f"• {text}                         {date}")
            row.setObjectName("Notice")
            layout.addWidget(row)

        layout.addStretch()
        return panel

    def create_history_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("최근 입출고 내역")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch()
        btn = QPushButton("전체 보기")
        btn.setObjectName("GhostButton")
        header.addWidget(btn)
        layout.addLayout(header)

        table = QTableWidget()
        table.setObjectName("HistoryTable")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["일시", "작업 구분", "품목", "장소", "변경 내용", "작업자"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setRowCount(5)

        rows = [
            ("2026.06.24 14:25", "입고", "산소", "현대케미칼", "실병 입고 +5", "관리자"),
            ("2026.06.24 14:20", "상태 변경", "질소 200bar", "현대케미칼", "실병 → 공병 -2 / +2", "관리자"),
            ("2026.06.24 14:15", "장소 이동", "404", "현대케미칼 → 예강창고", "실병 이동 -3 / +3", "관리자"),
            ("2026.06.24 14:10", "폐기", "아세틸렌", "현대케미칼", "폐기 처리 -1", "관리자"),
            ("2026.06.24 14:05", "입고", "407", "예강창고", "실병 입고 +4", "관리자"),
        ]

        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if c == 1:
                    if value == "입고":
                        item.setForeground(QColor("#059669"))
                    elif value == "폐기":
                        item.setForeground(QColor("#ef4444"))
                    else:
                        item.setForeground(QColor("#2563eb"))
                    item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                table.setItem(r, c, item)
            table.setRowHeight(r, 34)

        layout.addWidget(table)
        return panel


    def find_inventory_row(self, item_name, location):
        for row in self.rows:
            if row.item == item_name and row.location == location:
                return row

        sub_map = {
            "산소": "O₂",
            "아세틸렌": "C₂H₂",
            "질소 180bar": "N₂ 180bar",
            "질소 200bar": "N₂ 200bar",
            "404": "R-404A",
            "407": "R-407C",
        }
        new_row = InventoryRow(item_name, sub_map.get(item_name, ""), location, 0, 0, 0, 0)
        self.rows.append(new_row)
        return new_row

    def get_status_attr(self, status):
        return {
            "실병": "full",
            "공병": "empty",
            "리페어": "repair",
            "폐기": "disposal",
        }.get(status, "full")

    def apply_io_transaction(self, data):
        mode = data["mode"]
        item = data["item"]
        location = data["location"]
        status = data["status"]
        qty = data["qty"]
        company = data["company"] or "-"
        ship = data["ship"] or "-"
        cylinders = data["cylinders"]
        memo = data["memo"] or "-"

        row = self.find_inventory_row(item, location)
        attr = self.get_status_attr(status)
        before = getattr(row, attr)

        if mode == "입고":
            setattr(row, attr, before + qty)
            qty_text = f"+{qty}"
            before_after = f"{status} {before} → {before + qty}"
            work = "입고"
        elif mode == "출고":
            if before < qty:
                return False, f"{location}의 {item} {status} 재고가 부족합니다.\\n현재 {before}병 / 출고 요청 {qty}병"
            setattr(row, attr, before - qty)
            qty_text = f"-{qty}"
            before_after = f"{status} {before} → {before - qty}"
            work = "출고"
        else:
            to_location = data.get("to_location", location)
            to_status = data.get("to_status", status)

            if location == to_location and status == to_status:
                return False, "현재 장소/상태와 변경 후 장소/상태가 같습니다.\n변경할 장소나 상태를 선택해주세요."

            if before < qty:
                return False, f"{location}의 {item} {status} 재고가 부족합니다.\n현재 {before}병 / 변경 요청 {qty}병"

            target_row = self.find_inventory_row(item, to_location)
            target_attr = self.get_status_attr(to_status)
            target_before = getattr(target_row, target_attr)

            setattr(row, attr, before - qty)
            setattr(target_row, target_attr, target_before + qty)

            qty_text = str(qty)
            if location != to_location and status != to_status:
                work = "장소/상태변경"
            elif location != to_location:
                work = "장소이동"
            else:
                work = "상태변경"

            location = f"{location} → {to_location}" if location != to_location else location
            status = f"{status} → {to_status}" if status != to_status else status
            before_after = f"출발 {before} → {before - qty} / 도착 {target_before} → {target_before + qty}"

        if item == "아세틸렌":
            acetylene_location = data.get("to_location", data["location"]) if mode == "상태/장소 변경" else data["location"]
            acetylene_status = data.get("to_status", data["status"]) if mode == "상태/장소 변경" else data["status"]
            self.apply_acetylene_numbers(mode, acetylene_location, acetylene_status, company, ship, cylinders, memo)

        cylinder_text = ", ".join(cylinders) if cylinders else "-"
        now_text = datetime.now().strftime("%Y.%m.%d %H:%M")

        self.history_rows.insert(0, {
            "time": now_text,
            "work": work,
            "item": item,
            "status": status,
            "qty": qty_text,
            "location": location,
            "company": company,
            "ship": ship if mode == "출고" else "-",
            "cylinders": cylinder_text,
            "worker": self.worker_name,
            "memo": memo,
            "before_after": before_after if item != "아세틸렌" else f"{before_after} / {cylinder_text}",
        })

        self.save_all_to_database()
        self.enqueue_sync_event("io_transaction", {
            "work": work,
            "item": item,
            "status": status,
            "qty": qty_text,
            "location": location,
            "company": company,
            "ship": ship if mode == "출고" else "-",
            "cylinders": cylinder_text,
            "worker": self.worker_name,
            "memo": memo,
            "before_after": before_after if item != "아세틸렌" else f"{before_after} / {cylinder_text}",
            "snapshot": self.prepare_full_sync_payload(),
        })
        self.rebuild_pages_after_data_change()
        return True, f"{work} 저장 완료\\n{item} / {location} / {status} / {qty}병"

    def apply_acetylene_numbers(self, mode, location, status, company, ship, cylinders, memo):
        for number in cylinders:
            existing = None
            for cyl in self.acetylene_cylinders:
                if cyl["no"] == number:
                    existing = cyl
                    break

            if existing is None:
                existing = {
                    "no": number,
                    "status": "",
                    "location": "",
                    "last": "",
                    "company": "",
                    "ship": "",
                    "date": "",
                    "memo": "",
                }
                self.acetylene_cylinders.append(existing)

            if mode == "출고":
                existing.update({
                    "status": "출고중",
                    "location": "-",
                    "last": "출고",
                    "company": company or "-",
                    "ship": ship or "-",
                    "date": datetime.now().strftime("%Y.%m.%d"),
                    "memo": memo or "선박 납품",
                })
            elif mode == "입고":
                existing.update({
                    "status": "보유중" if status == "실병" else status,
                    "location": location,
                    "last": "입고",
                    "company": company or "-",
                    "ship": "-",
                    "date": datetime.now().strftime("%Y.%m.%d"),
                    "memo": memo or "입고",
                })
            else:
                existing.update({
                    "status": status,
                    "location": location,
                    "last": "상태변경",
                    "company": company or "-",
                    "ship": "-",
                    "date": datetime.now().strftime("%Y.%m.%d"),
                    "memo": memo or "상태/장소 변경",
                })

    def rebuild_pages_after_data_change(self):
        if not hasattr(self, "stack"):
            return

        current_index = self.stack.currentIndex()

        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()

        self.dashboard_page = self.create_dashboard_page()
        self.stock_page = self.create_stock_status_page()
        self.history_page = self.create_history_page()

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.stock_page)
        self.stack.addWidget(self.history_page)
        self.stack.setCurrentIndex(min(current_index, self.stack.count() - 1))

        page_key = "dashboard" if current_index == 0 else "stock" if current_index == 1 else "history"
        for key, btn in self.nav_buttons.items():
            active = key == page_key
            btn.setChecked(active)
            btn.setObjectName("SideButtonActive" if active else "SideButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def open_stock_dialog(self):
        dlg = StockChangeDialog(self.items, self.locations, self)
        if dlg.exec():
            data = getattr(dlg, "result_data", None)
            if not data:
                return
            ok, message = self.apply_io_transaction(data)
            if ok:
                QMessageBox.information(self, "저장 완료", message)
            else:
                QMessageBox.warning(self, "저장 실패", message)

    def open_item_dialog(self):
        dlg = ManageListDialog("품목 관리", self.items, self)
        if dlg.exec():
            if dlg.values != self.items:
                self.items = dlg.values
                self.save_all_to_database()
                self.enqueue_sync_event("items_updated", {"items": self.items, "snapshot": self.prepare_full_sync_payload()})
                self.rebuild_pages_after_data_change()

    def open_location_dialog(self):
        dlg = ManageListDialog("장소 관리", self.locations, self)
        if dlg.exec():
            if dlg.values != self.locations:
                self.locations = dlg.values
                self.save_all_to_database()
                self.enqueue_sync_event("locations_updated", {"locations": self.locations, "snapshot": self.prepare_full_sync_payload()})
                self.rebuild_pages_after_data_change()

    def apply_styles(self):
        self.setStyleSheet("""
        * {
            font-family: "Malgun Gothic", "Segoe UI";
        }

        QMainWindow {
            background: #f4f7fb;
        }

        #LoginTitle {
            color: #0f172a;
            font-size: 26px;
            font-weight: 900;
        }

        #LoginSub {
            color: #64748b;
            font-size: 13px;
            font-weight: 700;
        }

        #LoginFormBox {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }

        #LoginHint {
            color: #ef4444;
            background: #fff7f7;
            border: 1px solid #fecaca;
            border-radius: 8px;
            padding: 9px 12px;
            font-size: 12px;
            font-weight: 700;
        }

        #Sidebar {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #12305e, stop:0.55 #1e3a8a, stop:1 #4338ca);
        }

        #LogoIcon {
            min-width: 42px;
            min-height: 42px;
            border-radius: 12px;
            background: rgba(255,255,255,0.18);
            color: #ffffff;
            font-size: 26px;
            font-weight: 800;
        }

        #LogoTitle {
            color: #ffffff;
            font-size: 19px;
            font-weight: 800;
        }

        #LogoSub {
            color: rgba(255,255,255,0.74);
            font-size: 10px;
            letter-spacing: 1px;
        }

        #SideButton, #SideButtonActive {
            border: none;
            border-radius: 8px;
            text-align: left;
            padding-left: 18px;
            font-size: 15px;
            font-weight: 600;
        }

        #SideButton {
            color: rgba(255,255,255,0.86);
            background: transparent;
        }

        #SideButton:hover {
            background: rgba(255,255,255,0.10);
        }

        #SideButtonActive {
            color: #ffffff;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #6d5dfc);
        }

        #HelpBox {
            border-radius: 10px;
            background: rgba(255,255,255,0.10);
        }

        #HelpTitle {
            color: #ffffff;
            font-size: 14px;
            font-weight: 800;
        }

        #HelpSub {
            color: rgba(255,255,255,0.70);
            font-size: 12px;
            line-height: 160%;
        }

        #HelpButton {
            color: #ffffff;
            background: rgba(30,64,175,0.75);
            border: none;
            border-radius: 7px;
            min-height: 34px;
            font-weight: 700;
        }

        #Footer {
            color: rgba(255,255,255,0.60);
            font-size: 11px;
            padding-left: 4px;
        }

        #Content {
            background: #f4f7fb;
        }

        #Topbar {
            background: #ffffff;
            border-bottom: 1px solid #e2e8f0;
        }

        #SyncText {
            color: #2563eb;
            background: #eef4ff;
            border: 1px solid #bfdbfe;
            border-radius: 13px;
            padding: 5px 10px;
            font-size: 12px;
            font-weight: 800;
        }

        #ServerStatusValue {
            color: #2563eb;
            font-size: 14px;
            font-weight: 900;
        }

        #TopText, #AdminText {
            color: #0f172a;
            font-size: 12px;
        }

        #Bell {
            color: #0f172a;
            font-size: 20px;
        }

        #Avatar {
            min-width: 38px;
            min-height: 38px;
            border-radius: 19px;
            background: #e2e8f0;
            color: #cbd5e1;
            font-size: 32px;
        }

        #Card, #Panel {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }

        #Card:hover {
            border: 1px solid #cbd5e1;
        }

        #CardTitle {
            font-size: 14px;
            font-weight: 800;
        }

        #CardValue {
            color: #0f172a;
            font-size: 31px;
            font-weight: 900;
        }

        #CardSub {
            color: #64748b;
            font-size: 13px;
        }

        #CardIcon {
            min-width: 54px;
            min-height: 54px;
            font-size: 30px;
            font-weight: 900;
        }

        #PanelTitle {
            color: #0f172a;
            font-size: 16px;
            font-weight: 900;
        }

        #Filter, QComboBox, QLineEdit {
            min-height: 34px;
            border-radius: 8px;
            border: 1px solid #dbe4ef;
            background: #ffffff;
            color: #334155;
        }

        QLineEdit {
            padding: 0 10px;
        }

        QComboBox {
            padding-left: 12px;
            padding-right: 34px;
        }

        QComboBox:hover, QLineEdit:hover {
            border: 1px solid #93c5fd;
            background: #fbfdff;
        }

        QComboBox:focus, QLineEdit:focus {
            border: 1px solid #4f6df5;
            background: #ffffff;
        }

        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 32px;
            border-left: 1px solid #edf2f7;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #f8fafc;
        }

        QComboBox::drop-down:hover {
            background: #eef4ff;
        }

        QComboBox::down-arrow {
            image: none;
            width: 0px;
            height: 0px;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #64748b;
            margin-right: 10px;
        }

        QComboBox::down-arrow:on {
            border-top: none;
            border-bottom: 6px solid #4f6df5;
        }

        QComboBox QAbstractItemView {
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #dbe4ef;
            border-radius: 8px;
            padding: 6px;
            outline: 0px;
            selection-background-color: #eaf1ff;
            selection-color: #0f172a;
        }

        QComboBox QAbstractItemView::item {
            min-height: 30px;
            padding: 6px 10px;
            border-radius: 6px;
        }

        QComboBox QAbstractItemView::item:hover {
            background: #f1f5ff;
        }

        #PrimaryButton {
            color: #ffffff;
            background: #4f6df5;
            border: none;
            border-radius: 8px;
            min-height: 34px;
            padding: 0 14px;
            font-weight: 800;
        }

        #PrimaryButton:hover {
            background: #3f5ae0;
        }

        #GhostButton {
            color: #334155;
            background: #f8fafc;
            border: 1px solid #dbe4ef;
            border-radius: 8px;
            min-height: 34px;
            padding: 0 14px;
            font-weight: 700;
        }

        #DangerButton {
            color: #ffffff;
            background: #ef4444;
            border: none;
            border-radius: 8px;
            min-height: 34px;
            padding: 0 14px;
            font-weight: 800;
        }

        #QuickButton {
            text-align: left;
            padding-left: 18px;
            color: #0f172a;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 800;
        }

        #QuickButton:hover {
            background: #f8fafc;
            border: 1px solid #bfdbfe;
        }

        QCompleter QAbstractItemView {
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #bfdbfe;
            border-radius: 8px;
            padding: 6px;
            outline: 0px;
            selection-background-color: #eaf1ff;
            selection-color: #0f172a;
            font-size: 13px;
        }

        QCompleter QAbstractItemView::item {
            min-height: 28px;
            padding: 6px 10px;
            border-radius: 6px;
        }

        #HistorySummaryCard {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }

        #HistorySummaryValue {
            color: #0f172a;
            font-size: 28px;
            font-weight: 900;
        }

        #HistorySummaryIcon {
            min-width: 50px;
            min-height: 50px;
            font-size: 30px;
            font-weight: 900;
        }

        #DangerOutlineButton {
            color: #dc2626;
            background: #fff7f7;
            border: 1px solid #fecaca;
            border-radius: 8px;
            min-height: 34px;
            padding: 0 14px;
            font-weight: 800;
        }

        #DangerOutlineButton:hover {
            background: #fee2e2;
        }

        #DetailBadge {
            min-height: 30px;
            font-size: 13px;
            font-weight: 900;
        }

        #DetailText {
            color: #334155;
            font-size: 13px;
            line-height: 165%;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 12px;
        }

        #DetailSectionTitle {
            color: #0f172a;
            font-size: 14px;
            font-weight: 900;
        }

        #BeforeAfterBox {
            color: #0f172a;
            font-size: 13px;
            font-weight: 800;
            background: #eef4ff;
            border: 1px solid #bfdbfe;
            border-radius: 10px;
            padding: 12px;
        }

        #PageTitle {
            color: #0f172a;
            font-size: 24px;
            font-weight: 900;
        }

        #PageSub {
            color: #64748b;
            font-size: 13px;
            font-weight: 600;
        }

        #StockSummaryCard {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }

        #SmallMetricLabel {
            color: #64748b;
            font-size: 12px;
            font-weight: 800;
        }

        #SmallMetricValue {
            font-size: 13px;
            font-weight: 900;
        }

        #WarningPanel {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #fff7ed, stop:1 #ffffff);
            border: 1px solid #fed7aa;
            border-radius: 12px;
        }

        #WarningTitle {
            color: #9a3412;
            font-size: 16px;
            font-weight: 900;
        }

        #WarningRow {
            background: rgba(255,255,255,0.72);
            border: 1px solid #ffedd5;
            border-radius: 9px;
        }

        #WarningText {
            color: #334155;
            font-size: 12px;
            font-weight: 700;
        }

        #WarningBadge {
            min-width: 58px;
            min-height: 24px;
            border-radius: 12px;
            background: #ffedd5;
            color: #c2410c;
            font-size: 11px;
            font-weight: 900;
        }

        #TableHint {
            color: #64748b;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: 800;
        }

        #LocationSection {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
        }

        #LocationTitle {
            color: #0f172a;
            font-size: 18px;
            font-weight: 900;
        }

        #LocationSub {
            color: #64748b;
            font-size: 12px;
            font-weight: 600;
        }

        #LocationBadge {
            min-width: 72px;
            min-height: 34px;
            border-radius: 17px;
            background: #eef4ff;
            color: #4f6df5;
            font-size: 14px;
            font-weight: 900;
        }

        #MiniStatusCard {
            background: #f8fafc;
            border: 1px solid #edf2f7;
            border-radius: 10px;
        }

        #MiniStatusName {
            font-size: 11px;
            font-weight: 800;
        }

        #MiniStatusValue {
            font-size: 20px;
            font-weight: 900;
        }

        QTableWidget {
            background: #ffffff;
            border: 1px solid #edf2f7;
            border-radius: 8px;
            color: #0f172a;
            gridline-color: #e5e7eb;
            selection-background-color: #dbeafe;
            selection-color: #0f172a;
        }

        QHeaderView::section {
            background: #f8fafc;
            color: #475569;
            border: none;
            border-right: 1px solid #e5e7eb;
            border-bottom: 1px solid #e5e7eb;
            height: 34px;
            font-size: 12px;
            font-weight: 800;
        }

        QTableWidget::item {
            border-bottom: 1px solid #eef2f7;
            padding: 4px;
        }

        #More {
            color: #2563eb;
            font-size: 12px;
            font-weight: 800;
        }

        #Notice {
            color: #334155;
            font-size: 12px;
            padding-top: 5px;
            padding-bottom: 5px;
        }

        #DialogDesc {
            color: #64748b;
            font-size: 13px;
            padding-bottom: 4px;
        }

        #ModeButton, #ModeButtonActive {
            border-radius: 9px;
            font-size: 14px;
            font-weight: 900;
        }

        #ModeButton {
            color: #334155;
            background: #f8fafc;
            border: 1px solid #dbe4ef;
        }

        #ModeButton:hover {
            background: #eef4ff;
            border: 1px solid #bfdbfe;
        }

        #ModeButtonActive {
            color: #ffffff;
            background: #4f6df5;
            border: 1px solid #4f6df5;
        }

        #HintText {
            color: #ef4444;
            font-size: 12px;
            font-weight: 700;
        }

        #PreviewBox {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
        }

        #PreviewTitle {
            color: #0f172a;
            font-size: 13px;
            font-weight: 900;
        }

        #PreviewText {
            color: #334155;
            font-size: 12px;
            line-height: 150%;
        }

        #DialogTitle {
            color: #0f172a;
            font-size: 20px;
            font-weight: 900;
            padding-bottom: 8px;
        }

        QTextEdit {
            border: 1px solid #dbe4ef;
            border-radius: 8px;
            padding: 8px;
            background: #ffffff;
            color: #0f172a;
        }

        QListWidget {
            border: 1px solid #dbe4ef;
            border-radius: 8px;
            background: #ffffff;
            padding: 8px;
            color: #0f172a;
        }

        QListWidget::item {
            min-height: 34px;
            border-radius: 6px;
            padding-left: 8px;
        }

        QListWidget::item:selected {
            background: #dbeafe;
            color: #0f172a;
        }
        """)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    login = LoginDialog()
    if login.exec() != QDialog.Accepted:
        sys.exit(0)

    user_role, user_name = login.get_login_info()
    win = MainWindow(user_role=user_role, user_name=user_name)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
