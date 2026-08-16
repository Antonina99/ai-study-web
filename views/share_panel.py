# -*- coding: utf-8 -*-
"""
views/share_panel.py —— 对外分享链接 UI：生成 / 复制 / 管理 / 有效期

- 核心存储与短码逻辑见 core/share.py；
- 课程级分享入口在 Tab1 课程详情页；「整个平台」分享 + 全量管理在侧边栏；
- 分享链接格式：<对外访问地址>/?share=<短码>，打开后无需登录即可访问，
  同一局域网内任意设备浏览器均可打开（样式与交互与本站一致）。
"""

import streamlit as st

from core import share

# (展示文案, 有效小时数)；None 表示永久有效
VALIDITY_OPTIONS = [
    ("永久有效", None),
    ("1 天后过期", 24),
    ("3 天后过期", 72),
    ("7 天后过期", 168),
    ("30 天后过期", 720),
]


def base_url():
    """当前配置的对外访问基础地址（去末尾斜杠；为空时回退默认探测地址）。"""
    url = (st.session_state.get("share_base_url") or share.get_default_base_url()).strip()
    return url.rstrip("/") or share.get_default_base_url()


def _expiry_label(rec):
    if not rec.get("expires_at"):
        return "永久有效"
    return f"至 {rec['expires_at']}"


def _render_share_list(prefix="", target_type=None):
    """列出已生成的分享链接（可复制 / 撤销）。target_type 为 None 时展示全部。"""
    records = [r for r in share.list_shares()
               if target_type is None or r.get("target_type") == target_type]
    if not records:
        st.caption("（暂无已生成的分享链接）")
        return
    st.markdown("**已生成的分享链接**")
    for r in records:
        link = f"{base_url()}/?share={r['token']}"
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.caption(f"🔗 {r['label']}　·　{_expiry_label(r)}")
            c2.button(
                "撤销",
                key=f"{prefix}del_share_{r['token']}",
                help="撤销后该链接立即失效",
                on_click=share.delete_share,
                args=(r["token"],),
            )
            st.code(link)
    st.caption("💡 点击链接右上角复制图标即可复制；同一局域网内任意设备打开即可访问。")


def render_sidebar_share_panel():
    """侧边栏：对外访问地址配置 + 「整个平台」分享 + 分享链接管理。"""
    st.subheader("🔗 对外分享")
    base = st.text_input(
        "对外访问地址",
        value=base_url(),
        key="share_base_url_input",
        help="默认为本机局域网地址；如需公网访问，请部署到公网服务器或用内网穿透/端口映射后，改成公网地址。",
    )
    st.session_state["share_base_url"] = base.strip().rstrip("/")

    validity = st.selectbox(
        "分享有效期",
        options=[x[0] for x in VALIDITY_OPTIONS],
        key="share_validity_global",
    )
    if st.button("生成「整个平台」分享链接", key="btn_share_app"):
        hours = dict(VALIDITY_OPTIONS)[validity]
        share.create_share("app", label="整个平台", hours=hours)
        st.toast("✅ 平台分享链接已生成")

    _render_share_list(prefix="g_")


def render_course_share(item, career_direction=None):
    """Tab1 课程详情页：为当前课程生成对外分享链接（仅展示课程级链接）。"""
    with st.expander("🔗 对外分享本课程", expanded=False):
        st.caption("生成公开链接后，其他人无需登录即可在任意设备上查看本课程内容（样式与本站一致）。")
        validity = st.selectbox(
            "分享有效期",
            options=[x[0] for x in VALIDITY_OPTIONS],
            key=f"share_validity_{item['id']}",
        )
        if st.button("生成课程分享链接", type="primary", key=f"btn_share_{item['id']}"):
            hours = dict(VALIDITY_OPTIONS)[validity]
            share.create_share(
                "course",
                target_id=item["id"],
                label=item["name"],
                career_direction=career_direction,
                hours=hours,
            )
            st.toast("✅ 课程分享链接已生成")
        st.caption(f"对外访问地址：`{base_url()}`（可在左侧「对外分享」面板修改）")
        _render_share_list(prefix=f"c_{item['id']}_", target_type="course")
