"""Offline literal template and labelled placeholder, never AI photography."""
from html import escape
from agents.fixture import creative_topic

def make_prompt(brief,instruction=''):
    topic=creative_topic(brief['description'],brief['must_avoid'])
    details='、'.join(brief['must_include'])
    if instruction:details+='；创作要求：'+creative_topic(instruction,brief['must_avoid'])
    return {'subject':topic,'environment':'与主题相关的单一场景，空间位置清晰','composition':f"{brief['aspect_ratio']}画幅，主体突出，背景有层次",'lighting':'柔和自然光，保留明暗层次','camera':'自然透视，中等焦距，主体清晰','style':brief['style'],'color':'自然色彩，整体色调协调','mood':'由主题呈现的真实情绪','details':details,'negative_constraints':brief['must_avoid'],'confirmed':False,'generation_mode':'fixture'}
def placeholder(prompt,size):
    width,height=map(int,size.split('x'))
    subject=escape(prompt.get('subject',prompt['compiled_prompt'])[:80])
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#ddd7c7"/><stop offset="1" stop-color="#889c95"/></linearGradient></defs><rect width="{width}" height="{height}" fill="url(#g)"/><circle cx="{width*.5}" cy="{height*.42}" r="{min(width,height)*.18}" fill="#fff" opacity=".25"/><text x="50%" y="64%" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#172c28">离线占位图，非 AI 照片</text><text x="50%" y="70%" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#172c28">{subject}</text></svg>'''
    return svg.encode('utf-8'),'image/svg+xml','svg',width,height
