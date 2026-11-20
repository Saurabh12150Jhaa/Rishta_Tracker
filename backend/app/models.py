from typing import Any, Optional
from pydantic import BaseModel, Field


PROFILE_EDITABLE_FIELDS = [
    "full_name",
    "gender",
    "dob",
    "age",
    "time_of_birth",
    "place_of_birth",
    "height",
    "marital_status",
    "diet",
    "smoking_drinking",
    "avatar_url",
    "disambiguation_tag",
    "education",
    "college",
    "occupation",
    "company",
    "annual_ctc",
    "work_mode",
    "current_city",
    "hometown",
    "relocation_openness",
    "father_details",
    "mother_details",
    "siblings_details",
    "family_type",
    "family_location",
    "caste_community",
    "sub_caste",
    "gotra",
    "manglik",
    "kundli_status",
    "kundli_gunas",
    "kundli_notes",
    "gotra_clash_alert",
    "source_channel",
    "source_name",
    "source_phone",
    "primary_contact_name",
    "primary_contact_relation",
    "primary_contact_phone",
    "candidate_phone",
    "linkedin_or_social",
    "external_platform",
    "external_profile_id",
    "external_profile_url",
    "status",
    "ball_in_court",
    "pass_reason",
    "snooze_until",
    "priority",
    "our_biodata_sent",
    "our_photos_sent",
    "our_kundli_sent",
    "numbers_exchanged",
    "ai_fit_score",
    "fit_summary",
    "pre_call_brief",
    "shared_family_notes",
    "private_notes",
]


class LoginRequest(BaseModel):
    member_name: str
    pin: str


class CreateMemberRequest(BaseModel):
    name: str
    role: str = "family"
    pin: str
    avatar_color: str = "indigo"


class UpdateMemberRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    pin: Optional[str] = None
    avatar_color: Optional[str] = None


class RelativeCreateOrUpdate(BaseModel):
    name: str
    relation: str = "Mausi / Bua / Uncle"
    side: str = "Maternal"
    phone: Optional[str] = ""
    city: Optional[str] = ""
    notes: Optional[str] = ""


class CustomWhatsAppRequest(BaseModel):
    stage_or_goal: str
    recipient_type: str = "prospect_family"
    recipient_name: Optional[str] = ""
    language_tone: str = "Respectful Hinglish + English"


class UpdatePinRequest(BaseModel):
    member_name: str
    new_pin: str


class ProfileCreateOrUpdate(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    age: Optional[int] = None
    time_of_birth: Optional[str] = None
    place_of_birth: Optional[str] = None
    height: Optional[str] = None
    marital_status: Optional[str] = None
    diet: Optional[str] = None
    smoking_drinking: Optional[str] = None
    avatar_url: Optional[str] = None
    disambiguation_tag: Optional[str] = None

    education: Optional[str] = None
    college: Optional[str] = None
    occupation: Optional[str] = None
    company: Optional[str] = None
    annual_ctc: Optional[str] = None
    work_mode: Optional[str] = None
    current_city: Optional[str] = None
    hometown: Optional[str] = None
    relocation_openness: Optional[str] = None

    father_details: Optional[str] = None
    mother_details: Optional[str] = None
    siblings_details: Optional[str] = None
    family_type: Optional[str] = None
    family_location: Optional[str] = None
    caste_community: Optional[str] = None
    sub_caste: Optional[str] = None
    gotra: Optional[str] = None
    manglik: Optional[str] = None
    kundli_status: Optional[str] = None
    kundli_gunas: Optional[str] = None
    kundli_notes: Optional[str] = None
    gotra_clash_alert: Optional[str] = None

    source_channel: Optional[str] = None
    source_name: Optional[str] = None
    source_phone: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_relation: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    candidate_phone: Optional[str] = None
    linkedin_or_social: Optional[str] = None
    external_platform: Optional[str] = None
    external_profile_id: Optional[str] = None
    external_profile_url: Optional[str] = None

    status: Optional[str] = None
    ball_in_court: Optional[str] = None
    pass_reason: Optional[str] = None
    snooze_until: Optional[str] = None
    priority: Optional[str] = None

    our_biodata_sent: Optional[int] = None
    our_photos_sent: Optional[int] = None
    our_kundli_sent: Optional[int] = None
    numbers_exchanged: Optional[int] = None

    ai_fit_score: Optional[int] = None
    fit_summary: Optional[str] = None
    positives: Optional[list[str]] = None
    concerns: Optional[list[str]] = None
    missing_questions: Optional[list[str]] = None
    pre_call_brief: Optional[str] = None
    shared_family_notes: Optional[str] = None
    private_notes: Optional[str] = None


class InteractionCreate(BaseModel):
    interaction_type: str = "phone_call"
    title: str
    summary: Optional[str] = None
    raw_text: Optional[str] = None
    transcript: Optional[str] = None
    visibility: str = "shared"
    occurred_at: Optional[str] = None
    run_ai_update: bool = True


class FamilyVoteRequest(BaseModel):
    vote: str = Field(..., pattern="^(shortlist|discuss|pass)$")
    comment: Optional[str] = None


class FollowUpCreate(BaseModel):
    task: str
    due_date: Optional[str] = None
    assigned_to: Optional[str] = "Family"
    ball_in_court: Optional[str] = "us"


class ApplyImportRequest(BaseModel):
    target_profile_id: Optional[int] = None
    accepted_fields: dict[str, Any] = Field(default_factory=dict)
    positives: Optional[list[str]] = None
    concerns: Optional[list[str]] = None
    missing_questions: Optional[list[str]] = None
    fit_summary: Optional[str] = None
    ai_fit_score: Optional[int] = None
    pre_call_brief: Optional[str] = None
    create_follow_up: bool = True
    follow_up_task: Optional[str] = None
    follow_up_due_date: Optional[str] = None
    interaction_note: Optional[str] = None


class CompareProfilesRequest(BaseModel):
    profile_ids: list[int]
