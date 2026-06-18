from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class AgentOutput(BaseModel):
    agent: str
    assessment_id: str
    target_company: str
    buyer_company: str
    timestamp: str
    status: Literal["COMPLETE", "PARTIAL", "NEEDS_HUMAN_REVIEW"]
    confidence_score: float
    human_review_required: bool = False
    data_sources: list[str] = []


class MacroIndicator(BaseModel):
    year: int
    value: float
    unit: str


class CountryAssessment(AgentOutput):
    country: str
    gdp_growth_5yr: list[MacroIndicator]
    gdp_nominal_usd_bn: float
    inflation_rate_latest: float
    currency_code: str
    currency_trend: Literal["APPRECIATING", "STABLE", "DEPRECIATING", "VOLATILE"]
    political_stability_score: float
    ease_of_doing_business_rank: int
    corporate_tax_rate_pct: float
    currency_repatriation_laws: str
    risk_flags: list[str]
    narrative_summary: str


class SectorAssessment(AgentOutput):
    sector: str
    country: str
    market_size_usd_bn: float
    market_growth_rate_pct: float
    num_major_players: int
    top_3_players: list[str]
    regulatory_risk: Literal["HIGH", "MEDIUM", "LOW"]
    key_regulations: list[str]
    technology_disruption_risk: Literal["HIGH", "MEDIUM", "LOW"]
    sector_specific_kpis: dict
    risk_flags: list[str]
    narrative_summary: str


class CompanyAssessment(AgentOutput):
    company_name: str
    is_buy_side: bool
    revenue_latest_usd_m: float
    ebitda_latest_usd_m: float
    ebitda_margin_pct: float
    net_debt_usd_m: float
    net_debt_to_ebitda: float
    capex_usd_m: float
    revenue_growth_rate_pct: float
    key_shareholders: list[dict]
    management_quality_score: float
    recent_strategic_moves: list[str]
    sector_kpis: dict
    risk_flags: list[str]
    narrative_summary: str
    cash_position_usd_m: Optional[float] = None
    acquisition_capacity_usd_m: Optional[float] = None
    stated_strategic_priorities: Optional[list[str]] = None
    previous_acquisitions: Optional[list[str]] = None


class Risk(BaseModel):
    title: str
    category: Literal["GEOPOLITICAL", "CURRENCY", "REGULATORY", "MARKET", "COMPANY", "CROSS_WORKSTREAM"]
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    probability: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    mitigants: list[str] = []
    is_cross_workstream: bool = False


class RiskAssessment(AgentOutput):
    overall_risk_rating: Literal["RED", "AMBER", "GREEN"]
    risks: list[Risk]
    cross_workstream_insights: list[str]


class ValueCreationAvenue(BaseModel):
    category: Literal["NEW_PRODUCTS", "NEW_CUSTOMERS", "ASSET_MONETIZATION", "COST_SYNERGY", "REVENUE_SYNERGY"]
    description: str
    estimated_impact: Literal["HIGH", "MEDIUM", "LOW"]
    requires_integration: bool


class DealRationale(AgentOutput):
    decision: Literal["GO", "NO_GO", "REVISIT"]
    revisit_timeframe: Optional[str] = None
    decision_rationale: list[str]
    value_creation_avenues: list[ValueCreationAvenue]
    ev_ebitda_comparable_range: dict
    implied_valuation_range_usd_m: dict
    key_conditions_for_reversal: list[str]
    recommended_next_steps: list[str]
    strategic_fit_score: float
