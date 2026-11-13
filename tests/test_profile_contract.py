import json
import pytest
from pydantic import ValidationError

def test_known_fact_requires_evidence():
    from wechat_agent.profiles.contracts import Fact
    with pytest.raises(ValidationError):
        Fact(value='12方',state='known',sources=[])

def test_missing_fact_never_invents_content():
    from wechat_agent.profiles.contracts import Fact
    fact=Fact()
    assert fact.value is None and fact.state=='not_mentioned' and fact.sources==[]
    with pytest.raises(ValidationError):Fact(value='德国',state='not_mentioned')

@pytest.mark.parametrize('revision',[0,-1,True])
def test_reference_requires_positive_integer_revision(revision):
    from wechat_agent.profiles.contracts import SourceRef
    with pytest.raises(ValidationError):SourceRef(message_id='m1',revision=revision)

def test_evidence_preserves_unit_and_aware_event_time():
    from wechat_agent.profiles.contracts import Fact
    fact=Fact(value='约12方',state='known',sources=[dict(message_id='m1',revision=2)],event_time='2026-11-13T08:00:00+08:00')
    assert fact.value=='约12方' and fact.sources[0].revision==2
    with pytest.raises(ValidationError):Fact(value='12方',state='known',sources=[dict(message_id='m1',revision=1)],event_time='2026-11-13T08:00:00')

def test_communication_conflict_is_located_at_tags():
    from wechat_agent.profiles.contracts import Communication
    with pytest.raises(ValidationError) as error:Communication(tags=['暂无新需求记录','询价中'])
    assert error.value.errors()[0]['loc']==('tags',)
    assert Communication().tags==[]
    assert Communication(tags=['初步沟通','暂无新需求记录']).tags==['初步沟通','暂无新需求记录']

def test_fixed_fields_reject_custom_content_and_model_owned_extras():
    from wechat_agent.profiles.contracts import AnalysisResult
    result=AnalysisResult(contact_id='merchant-a')
    assert set(result.goods.model_dump())=={'category','products','special_attributes','volume'}
    assert len(result.logistics.model_dump())==9
    assert result.goods.category.value is None
    for extra in ({'coverage':{}},{'manual':{}},{'nickname':'猜名'},{'goods':{'custom':'其它'}}):
        with pytest.raises(ValidationError):AnalysisResult(contact_id='merchant-a',**extra)
    assert json.loads(json.dumps(result.model_json_schema()))['additionalProperties'] is False

def test_shipments_are_independent_and_numbers_do_not_determine_stage():
    from wechat_agent.profiles.contracts import AnalysisResult,ShipmentCandidate
    old=ShipmentCandidate(existing_id='old',candidate_key='old-demand',stage='已走货')
    new=ShipmentCandidate(candidate_key='new-demand',stage='询价',numbers=['A-1'])
    result=AnalysisResult(contact_id='merchant-a',shipments=[old,new])
    assert [item.stage for item in result.shipments]==['已走货','询价']
    with pytest.raises(ValidationError):ShipmentCandidate(candidate_key='bad',stage='完成全部客户')

def test_collections_are_independent_and_identity_is_explicit():
    from wechat_agent.profiles.contracts import AnalysisResult
    one=AnalysisResult(contact_id='a');two=AnalysisResult(contact_id='b')
    one.gaps.append('missing_material')
    assert two.gaps==[]
    with pytest.raises(ValidationError):AnalysisResult(contact_id=' ')
    with pytest.raises(ValidationError):AnalysisResult(contact_id='a',schema_version=2)
