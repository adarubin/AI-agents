from datetime import date

from job_agent.qualifications import gaps, experience_gaps
from tests.test_eligibility import job

PROFILE = {'experience_facts': {'years_professional_ml': 1, 'years_robotics': 3},
           'education': {'expected_graduation_month': '2027-03'}}


def posting(requirements):
    result = job()
    result.description_text += '\nRequirements\n' + requirements
    return result


def test_total_engineering_experience_does_not_satisfy_required_ml_years():
    result = experience_gaps(posting('2+ years of practical experience developing computer vision or machine learning solutions using Python.'), PROFILE)
    assert len(result) == 1
    assert 'documented years_professional_ml=1' in result[0]


def test_robotics_and_ml_experience_are_distinct():
    assert not experience_gaps(posting('3 years of control design experience and programming.'), PROFILE)
    assert experience_gaps(posting('4+ years of robotics experience.'), PROFILE)
    assert not gaps(posting('4+ years of robotics experience.'), PROFILE)


def test_preferred_experience_does_not_become_mandatory():
    assert not experience_gaps(posting('Strong Python.\nPreferred Qualifications\n5+ years of machine learning experience.'), PROFILE)


def test_semesters_remaining_are_checked_against_graduation():
    result = gaps(posting('M.Sc. student with at least 3 semesters until graduation'), PROFILE, date(2026, 10, 15))
    assert result


def test_company_history_is_not_a_candidate_requirement():
    result = job()
    result.description_text += '\nWe have over 20 years developing computer vision.'
    assert not gaps(result, PROFILE)


def test_inline_html_line_breaks_cannot_hide_required_ml_experience():
    assert experience_gaps(posting('2+ years of practical experience\ndeveloping computer vision or machine learning solutions.'), PROFILE)


def test_completed_degree_requirement_and_bachelors_alternative():
    profile = {'experience_facts': {'masters_completed': False}}
    assert gaps(posting('M.Sc. or Ph.D. in Mathematics, Physics or Computer Science.'), profile)
    assert not gaps(posting('B.Sc. or M.Sc. in Computer Science or a related field.'), profile)
    assert not gaps(posting('Python coding.\nNice to have\nM.Sc. in a relevant field.'), profile)


def test_preferred_specialization_does_not_cancel_mandatory_experience():
    assert experience_gaps(posting('4+ years of hands-on experience developing deep learning algorithms, preferably in computer vision.'), PROFILE)


def test_degree_after_requirements_subheading_is_still_required():
    profile = {'experience_facts': {'masters_completed': False}}
    assert gaps(posting('What are we looking for? M.Sc. / Ph.D. in Electrical Engineering or Computer Science.'), profile)
