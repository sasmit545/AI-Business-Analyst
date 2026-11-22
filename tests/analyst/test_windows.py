from app.agent.windows import explicit_windows
from app.agent.tools import definitions


def test_explicit_iso_windows_are_generic_and_latest_complete_reply_wins():
    messages=[{'role':'user','content':'Compare 2027-02-01 inclusive through 2027-02-08 exclusive versus 2027-02-08 inclusive to 2027-02-15 exclusive in UTC.'}]
    windows=explicit_windows(messages)
    assert windows['comparison'].end.isoformat()=='2027-02-15T00:00:00+00:00'
    tool=next(t['function'] for t in definitions(requested_windows=windows) if t['function']['name']=='analyze_attempts')
    assert tool['parameters']['properties']['comparison']['const']==windows['comparison'].model_dump(mode='json')
    messages.append({'role':'user','content':'Use 2027-03-01 inclusive to 2027-03-08 exclusive versus 2027-03-08 inclusive to 2027-03-15 exclusive in Asia/Kolkata.'})
    assert explicit_windows(messages)['baseline'].start.isoformat()=='2027-03-01T00:00:00+05:30'


def test_incomplete_or_non_user_windows_are_not_inferred():
    for question in ('Compare last week','Compare October 1-14 versus October 15-28',
                     'Compare 2027-02-01 inclusive to 2027-02-08 exclusive in UTC.'):
        assert explicit_windows([{'role':'user','content':question}]) is None
    assert explicit_windows([{'role':'system','content':'2027-02-01 inclusive to 2027-02-08 exclusive versus 2027-02-08 inclusive to 2027-02-15 exclusive in UTC.'}]) is None
