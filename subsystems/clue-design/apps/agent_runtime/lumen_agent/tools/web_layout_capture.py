"""Bounded geometry/style observations from the same page as a saved preview.

This is a measurement aid, not a source-fidelity or aesthetic judge. It never
rewrites the page, executes source scripts, fetches assets, or certifies fidelity.
"""

from collections import deque
from typing import Any

from .web_font_capture import capture_glyph_fonts

MAX_LAYOUT_NODES = 48


def layout_targets(web_doc: dict, page_id: str) -> list[dict]:
    """Reachable sections and fragment pins on the selected page, in tree order."""
    page = next((p for p in web_doc.get("pages", []) if p.get("id") == page_id), None)
    if page is None:
        return []
    nodes = page.get("nodes") or {}
    pending = deque([page.get("root")])
    seen = set()
    targets = []
    while pending:
        key = pending.popleft()
        if not isinstance(key, str) or key in seen:
            continue
        seen.add(key)
        node = nodes.get(key)
        if not isinstance(node, dict):
            continue
        pending.extend(node.get("children") or [])
        if node.get("kind") in {"section", "fragment"}:
            targets.append(
                {"node_id": key, "kind": node["kind"], "fragment_id": node.get("fragment_id")}
            )
    return targets


_LAYOUT_SCRIPT = r"""
({targets}) => {
  const cap = 16, scanCap = 5000;
  const round = n => Math.round(n * 100) / 100;
  const box = el => { const r=el.getBoundingClientRect(); return {
    x:round(r.x+scrollX), y:round(r.y+scrollY), width:round(r.width), height:round(r.height)
  }; };
  const short = value => String(value || '').slice(0,512);
  const source = value => {
    const text=String(value || '');
    const match=text.match(/\/asset-store\/([a-f0-9]{64})(?:[^a-f0-9]|$)/);
    return {asset_digest:match ? match[1] : null,
      source: text.startsWith('data:')
        ? short(text.split(',')[0])+',[inline bytes omitted]' : short(text)};
  };
  const background = value => short(String(value).replace(
    /url\(["']?data:[^)]+\)/gi,'url([inline bytes omitted])'));
  const computed = (el,kind) => {
    const s=getComputedStyle(el);
    const base={display:s.display,visibility:s.visibility,opacity:s.opacity};
    if(kind==='text') return {...base,
      font_family:short(s.fontFamily),font_size:s.fontSize,font_weight:s.fontWeight,
      line_height:s.lineHeight,letter_spacing:s.letterSpacing,color:s.color,
      text_align:s.textAlign,font_synthesis:s.fontSynthesis};
    const frame={border_radius:s.borderRadius,border_width:s.borderWidth,
      background_color:s.backgroundColor,background_image:background(s.backgroundImage)};
    if(kind==='image') return {...base,...frame,
      object_fit:s.objectFit,object_position:s.objectPosition};
    return {...base,...frame,padding:s.padding,gap:s.gap,min_height:s.minHeight,
      max_height:s.maxHeight,align_items:s.alignItems,justify_content:s.justifyContent,
      overflow_x:s.overflowX,overflow_y:s.overflowY};
  };
  const visible = el => {
    let r=el.getBoundingClientRect(), left=r.left,right=r.right,top=r.top,bottom=r.bottom;
    const own=getComputedStyle(el);
    // Inherited visibility can be overridden by the target; display and opacity cannot.
    if(own.visibility==='hidden'||own.visibility==='collapse') return false;
    for(let p=el;p;p=p.parentElement){
      const s=getComputedStyle(p);
      if(s.display==='none'||Number(s.opacity)===0) return false;
      if(p!==el && p!==document.documentElement && p!==document.body && s.display!=='contents'){
        const b=p.getBoundingClientRect();
        if(s.overflowX!=='visible'){left=Math.max(left,b.left);right=Math.min(right,b.right);}
        if(s.overflowY!=='visible'){top=Math.max(top,b.top);bottom=Math.min(bottom,b.bottom);}
      }
    }
    // display:contents owns text without an element box. Do not call it hidden.
    if(own.display==='contents') return null;
    return right>left && bottom>top;
  };
  const path = (el,root) => {
    const parts=[]; for(let p=el;p && p!==root;p=p.parentElement){
      const index=Array.from(p.parentElement.children).indexOf(p)+1;
      parts.unshift(':nth-child('+index+')');
    } return parts.join(' > ');
  };
  const describe = (el,root,kind='container') => {
    const cssVisible=visible(el);
    return {tag:el.tagName.toLowerCase(),rendered_path:path(el,root),box:box(el),
      computed:computed(el,kind),css_visible:cssVisible,
      ...(cssVisible===null?{visibility_note:'no_element_box_direct_text_unmeasured'}:{})};
  };
  const textOwnerIds=new Map();
  const nodes=targets.map(target=>{
    const matches=document.querySelectorAll('[data-node-id="'+CSS.escape(target.node_id)+'"]');
    if(matches.length!==1) return {...target,status:matches.length?'ambiguous':'missing'};
    const root=matches[0], all=[root,...root.querySelectorAll('*')], scanned=all.slice(0,scanCap);
    // Shared wrappers are described once; repeated product rows must not flood context.
    const containers={}, containerIds=new Map();
    const containerId = el => {
      if(!containerIds.has(el)){
        const id='c'+containerIds.size;
        containerIds.set(el,id); containers[id]=describe(el,root);
      }
      return containerIds.get(el);
    };
    const textNodes=scanned.filter(el=>!el.closest('script,style,noscript,template,svg,math') &&
      Array.from(el.childNodes).some(n=>n.nodeType===3 && n.textContent.trim()));
    const imgs=scanned.filter(el=>el.tagName==='IMG');
    const texts=textNodes.slice(0,cap).map(el=>{
      if(!textOwnerIds.has(el)) textOwnerIds.set(el,'t'+textOwnerIds.size);
      const direct=Array.from(el.childNodes).filter(n=>n.nodeType===3)
        .map(n=>n.textContent).join('').replace(/\s+/g,' ').trim();
      const role=el.closest('h1,h2,h3,h4,h5,h6,p,button,a,summary,label');
      return {...describe(el,root,'text'),text_owner_id:textOwnerIds.get(el),
        text:direct.slice(0,240),text_complete:direct.length<=240,
        role:role && root.contains(role)?role.tagName.toLowerCase():el.tagName.toLowerCase(),
        parent_container_id:el===root?null:containerId(el.parentElement)};
    });
    const images=imgs.slice(0,cap).map(el=>{
      const ancestors=[];
      for(let p=el.parentElement;p && root.contains(p) && ancestors.length<3;p=p.parentElement){
        ancestors.push(containerId(p));
      }
      return {...describe(el,root,'image'),...source(el.currentSrc || el.getAttribute('src')),
        alt:short(el.alt), natural_width:el.naturalWidth,natural_height:el.naturalHeight,
        loaded:el.complete && el.naturalWidth>0,pixel_composition:'unclassified',
        ancestor_container_ids:ancestors};
    });
    return {...target,...describe(root,root),status:'measured',texts,images,containers,
      complete:all.length<=scanCap && textNodes.length<=cap && imgs.length<=cap,
      omitted:{descendants:Math.max(0,all.length-scanCap),texts:Math.max(0,textNodes.length-cap),
               images:Math.max(0,imgs.length-cap)}};
  });
  const faces=Array.from(document.fonts);
  return {schema_version:1,viewport_width:innerWidth,
    document_height:document.documentElement.scrollHeight,
    document_width:document.documentElement.scrollWidth,
    root_font_size:getComputedStyle(document.documentElement).fontSize,
    scope:'default_preview_state',coordinate_space:'document_css_pixels',
    path_space:'rendered_node_relative',text_owner_id_scope:'this_capture_only',
    visibility_basis:'css_box_and_ancestor_clipping_not_occlusion',
    actual_glyph_font:'not_measured',quality_verdict:'not_computed',fonts_status:document.fonts.status,
    declared_font_faces:faces.slice(0,32).map(f=>({
      family:short(f.family),weight:f.weight,style:f.style,status:f.status})),
    font_faces_omitted:Math.max(0,faces.length-32),nodes,
    note:'Measured just after the default screenshot on the same browser page, '
      +'not a synchronized animation frame. Computed family is a CSS stack, '
      +'not proof of the face used for glyphs; see bounded per-text font_usage. '
      +'Image pixels/alpha and baked framing '
      +'are not classified. Rendered paths are not stored edit paths. Measurements '
      +'do not establish source parity, all states or aesthetic quality.'};
}
"""


def capture_layout(page: Any, targets: list[dict]) -> dict:
    """Observe under fixed caps; never turn an exception into an empty clean report."""
    try:
        result = page.evaluate(_LAYOUT_SCRIPT, {"targets": targets[:MAX_LAYOUT_NODES]})
        if not isinstance(result, dict) or not isinstance(result.get("nodes"), list):
            raise ValueError("invalid layout observation")
        result["status"] = "observed"
        result["omitted_node_ids"] = [r["node_id"] for r in targets[MAX_LAYOUT_NODES:]]
        result["glyph_font_capture"] = capture_glyph_fonts(page, result["nodes"])
        result["actual_glyph_font"] = "see_per_text_font_usage"
        return result
    except Exception as error:
        return {
            "status": "unavailable",
            "code": "layout.capture_failed",
            "error_type": type(error).__name__,
            "nodes": [],
            "quality_verdict": "not_computed",
        }
