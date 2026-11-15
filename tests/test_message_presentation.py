import json
import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.repository import archive_page

@pytest.mark.parametrize('kind,body,expected',[
 ('merged_messages','转发的实际内容','[转发聊天记录]'),
 ('text',json.dumps({'MergedMessages':{'title':'聊天记录','raw_xml':'<msg>private</msg>'}}),'[转发聊天记录]'),
 ('image',json.dumps({'Image':{'raw_xml':'<msg>secret</msg>'}}),'[图片]'),
 ('voice',json.dumps({'Voice':{'raw_xml':'<msg>secret</msg>'}}),'[语音]'),
 ('video','<msg><videomsg aeskey="secret"/></msg>','[视频]'),
 ('file',json.dumps({'File':{'title':'合同.docx','raw_xml':'secret'}}),'合同.docx'),
 ('quote',json.dumps({'Quote':{'reply_text':'请帮我报价','raw_xml':'secret'}}),'请帮我报价'),
 ('app',json.dumps({'Link':{'title':'运输方案','raw_xml':'secret'}}),'[链接] 运输方案'),
 ('unknown',json.dumps({'Location':{'raw_xml':'secret'}}),'[位置]'),
 ('unknown',json.dumps({'Emoji':{'raw_xml':'secret'}}),'[表情]'),
 ('app','<?xml version="1.0"?><msg><appmsg/></msg>','[应用消息]'),
 ('unknown',json.dumps({'Unknown':{'secret':'hidden'}}),'[暂不支持展示的消息]'),
 ('text','普通中文、[图片]文字和 < 12 方','普通中文、[图片]文字和 < 12 方'),
 ('text','{"quantity":12}','{"quantity":12}'),
 ('file','合同.docx','合同.docx'),
])
def test_special_message_display(kind,body,expected):
 from wechat_agent.messages.presentation import display_body
 assert display_body(kind,body)==expected

def test_timeline_simplifies_forward_but_keeps_archive_intact(db):
 from wechat_agent.api.messages import read_timeline
 seed_case(db)
 original=json.dumps({'MergedMessages':{'title':'群聊的聊天记录','raw_xml':'<msg>private-secret</msg>'}})
 archive_page(db,make_page([make_message(message_id='forward-special',kind='merged_messages',body=original)]))
 result=read_timeline(db,'acct-1','merchant-a')
 assert next(item for item in result['items'] if item['message_id']=='forward-special')['body']=='[转发聊天记录]'
 assert db.execute("SELECT body FROM messages WHERE message_id='forward-special'").fetchone()[0]==original

@pytest.mark.parametrize('tag',['voicemsg','videomsg','emoji','location'])
def test_wire_xml_without_msg_wrapper_is_not_displayed(tag):
 from wechat_agent.messages.presentation import display_body
 assert display_body('unknown',f'<{tag} aeskey="secret"/>')=='[暂不支持展示的消息]'

def test_oversized_forward_envelope_is_not_displayed_as_text():
 from wechat_agent.messages.presentation import display_body
 body=json.dumps({'MergedMessages':{'raw_xml':'x'*300000}})
 assert display_body('text',body)=='[转发聊天记录]'

def test_normal_json_mentioning_variant_name_remains_text():
 from wechat_agent.messages.presentation import display_body
 body='{"note":"MergedMessages"}'
 assert display_body('text',body)==body
