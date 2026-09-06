# -*- coding: utf-8 -*-
"""工作台视觉组件：加载主题、渲染页面标题、状态标签与指标卡。"""

from html import escape
from pathlib import Path

import streamlit as st
import streamlit_shadcn_ui as ui


_STYLE_FILE = Path(__file__).resolve().parent.parent / "assets" / "styles.css"


def apply_workspace_theme():
    """加载项目级工作台 CSS。"""
    st.markdown(f"<style>{_STYLE_FILE.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def render_workspace_header(title, subtitle, eyebrow="LEARNING WORKSPACE", status="文字学习模式"):
    """渲染紧凑的工作台页面标题。"""
    st.markdown(
        f"""
        <section class="workspace-hero">
          <div>
            <div class="workspace-eyebrow">{escape(eyebrow)}</div>
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
          </div>
          <span class="workspace-status"><i></i>{escape(status)}</span>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_badges(items, key):
    """使用 Shadcn Badge 渲染紧凑标签组。"""
    values = [(str(item), "secondary") for item in items if item]
    if values:
        ui.badges(values, key=key)


def render_metric(label, value, description, key, variant="default"):
    """使用 Shadcn 指标卡渲染工作台摘要。"""
    ui.metric_card(
        label=label,
        value=value,
        description=description,
        variant=variant,
        key=key,
        size="sm",
    )


def render_navigation(options, key):
    """使用 Shadcn Tabs 渲染应用级工作台导航。"""
    return ui.tabs(options=options, value=options[0], key=key, label="工作台导航")


def render_progress(value, label, key):
    """使用 Shadcn Progress 渲染紧凑进度条。"""
    ui.progress(value=value * 100, label=label, show_value=True, key=key)


def render_section_heading(title, description=None):
    """渲染卡片区域标题。"""
    description_html = f"<p>{escape(description)}</p>" if description else ""
    st.markdown(
        f'<div class="workspace-section-title"><h3>{escape(title)}</h3>{description_html}</div>',
        unsafe_allow_html=True,
    )
