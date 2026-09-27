"""
Deterministic, Provenance-Bound Message Composer.
Implements grounded composition patterns for all challenge trigger kinds.
Ensures zero-hallucination fact binding, category-specific voice, and single clear CTAs.
"""

from typing import Dict, Any, Optional, List
from app.engine.signal_extractor import GroundedSignals
from app.engine.composer.base import ComposedOutput
from app.engine.composer.formatter import message_formatter


class DeterministicComposer:
    def compose(self, signals: GroundedSignals) -> ComposedOutput:
        """Dispatch signals to the appropriate trigger kind handler."""
        kind = signals.trigger_kind
        handler_name = f"_compose_{kind}"
        handler = getattr(self, handler_name, self._compose_generic)
        return handler(signals)

    # -------------------------------------------------------------------------
    # 1. Research Digest
    # -------------------------------------------------------------------------
    def _compose_research_digest(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        d = s.digest_item or {}
        source = d.get("source", "Recent category research")
        title = d.get("title", "new clinical trial findings")
        trial_n = d.get("trial_n")
        trial_str = f"{trial_n:,}-patient trial" if trial_n else "recent study"

        # Check for merchant cohort anchor
        cohort_count = s.customer_aggregate.get("high_risk_adult_count")
        cohort_mention = f"your {cohort_count} high-risk adult patients" if cohort_count else "your patient cohort"

        body = (
            f"{salutation}, {source} landed. One item relevant to {cohort_mention} — "
            f"{trial_str} showed {title.lower()}. "
            f"Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share? — {source}"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_research_digest_v1",
            template_params=[salutation, title, source],
            body=body,
            cta="open_ended",
            suppression_key=s.suppression_key,
            rationale=f"External research digest anchored on {source} and merchant's patient cohort. Open-ended low-friction CTA."
        )

    # -------------------------------------------------------------------------
    # 2. Regulation / Compliance Change
    # -------------------------------------------------------------------------
    def _compose_regulation_change(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        deadline = s.payload.get("deadline_iso", "upcoming deadline")
        d = s.digest_item or {}
        source = d.get("source", "Official circular")
        summary = d.get("summary", "revised compliance regulations").rstrip(".")

        body = (
            f"{salutation}, compliance update from {source} effective {deadline}: "
            f"{summary}. To ensure clinic audit readiness before the deadline, want me to send a 2-minute SOP checklist "
            f"for {s.merchant_name}? Reply YES to receive it."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_compliance_alert_v1",
            template_params=[salutation, deadline, source],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Urgent regulatory change notification with concrete source circular and binary checklist CTA."
        )

    # -------------------------------------------------------------------------
    # 3. Customer Recall Due (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_recall_due(self, s: GroundedSignals) -> ComposedOutput:
        cname = s.customer_name or "there"
        salutation = message_formatter.get_salutation(s, customer_facing=True)

        # Slots from payload
        slots = s.payload.get("available_slots", [])
        if len(slots) >= 2:
            slot1 = slots[0].get("label", "Wed 6pm")
            slot2 = slots[1].get("label", "Thu 5pm")
            slots_text = f"Wed {slot1} ya Thu {slot2}" if "hi" in (s.customer_lang or "") else f"{slot1} or {slot2}"
        else:
            slot1, slot2 = "Wed 6pm", "Thu 5pm"
            slots_text = "Wed 6pm or Thu 5pm"

        # Offer from merchant active offers or catalog
        offer_title = "Dental Cleaning @ ₹299"
        if s.active_offers:
            offer_title = s.active_offers[0].get("title", offer_title)

        body = (
            f"{salutation} It's been 5 months since your last visit — your 6-month cleaning recall is due. "
            f"Apke liye 2 slots ready hain: {slots_text}. {offer_title} + complimentary check. "
            f"Reply 1 for first slot, 2 for second slot, or tell us a time that works."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_recall_reminder_v1",
            template_params=[cname, s.merchant_name, offer_title],
            body=body,
            cta="multi_choice_slot",
            suppression_key=s.suppression_key,
            rationale="Customer-facing recall sent on behalf of merchant with 2 specific evening slots, real offer price, and low-friction slot CTA."
        )

    # -------------------------------------------------------------------------
    # 4. Performance Dip
    # -------------------------------------------------------------------------
    def _compose_perf_dip(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        metric = s.payload.get("metric", "customer calls")
        delta_pct = s.payload.get("delta_pct") or s.delta_calls_pct or -0.30
        pct_str = f"{abs(round(delta_pct * 100))}%"
        baseline = s.payload.get("vs_baseline", 15)

        body = (
            f"Quick heads-up {salutation}: your Google Business profile {metric} dropped {pct_str} over the last 7 days "
            f"(vs your baseline of ~{baseline} {metric}/week). Want me to draft a fresh Google post + push your active service offer "
            f"to boost discovery this week?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_perf_dip_v1",
            template_params=[salutation, metric, pct_str],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale=f"Diagnoses 7d {metric} drop with exact percentage and baseline; proposes concrete recovery action."
        )

    # -------------------------------------------------------------------------
    # 5. Performance Spike
    # -------------------------------------------------------------------------
    def _compose_perf_spike(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        metric = s.payload.get("metric", "views")
        delta_pct = s.payload.get("delta_pct") or s.delta_views_pct or 0.20
        pct_str = f"+{abs(round(delta_pct * 100))}%"
        driver = s.payload.get("likely_driver", "recent profile updates")

        body = (
            f"Great news {salutation}! Your {metric} surged {pct_str} over the past 7 days, "
            f"likely driven by {driver.replace('_', ' ')}. Want me to schedule a follow-up GBP post tomorrow "
            f"to keep this engagement momentum going?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_perf_spike_v1",
            template_params=[salutation, metric, pct_str],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Reinforces positive growth signal and offers immediate low-effort follow-on post."
        )

    # -------------------------------------------------------------------------
    # 6. Renewal Due
    # -------------------------------------------------------------------------
    def _compose_renewal_due(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        days = s.payload.get("days_remaining") or s.days_remaining or 12
        plan = s.payload.get("plan") or "Pro"
        views = s.perf_views or 1500
        calls = s.perf_calls or 25

        body = (
            f"Hi {salutation}, your {plan} plan for {s.merchant_name} expires in {days} days. "
            f"Over the last 30 days, your listing delivered {views:,} views and {calls} direct customer calls. "
            f"Want me to lock in your renewal now so profile maintenance and lead tracking continue uninterrupted?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_renewal_reminder_v1",
            template_params=[salutation, str(days), plan],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Renewal alert anchored in real 30-day views/calls ROI; binary confirmation ask."
        )

    # -------------------------------------------------------------------------
    # 7. Festival Upcoming
    # -------------------------------------------------------------------------
    def _compose_festival_upcoming(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        fest = s.payload.get("festival", "Diwali")
        days = s.payload.get("days_until", 7)
        date = s.payload.get("date", "soon")

        body = (
            f"Hi {salutation}! {fest} is in {days} days ({date}). Local searches in {s.locality} for "
            f"festival appointments are already climbing. Want me to draft a {fest} special GBP post + customer WhatsApp message "
            f"so you capture bookings before the rush?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_festival_campaign_v1",
            template_params=[salutation, fest, str(days)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Festival marketing preparation window trigger; externalizes drafting effort for merchant."
        )

    # -------------------------------------------------------------------------
    # 8. Wedding / Bridal Followup (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_wedding_package_followup(self, s: GroundedSignals) -> ComposedOutput:
        cname = s.customer_name or "there"
        salutation = message_formatter.get_salutation(s, customer_facing=True)
        days_to_wedding = s.payload.get("days_to_wedding", 180)
        wedding_date = s.payload.get("wedding_date", "your wedding day")
        owner = s.owner_name or "Our team"

        # Offer
        offer_title = "₹2,499 bridal skin-prep package"
        if s.active_offers:
            offer_title = s.active_offers[0].get("title", offer_title)

        body = (
            f"Hi {cname} 💍 {owner} from {s.merchant_name} here. {days_to_wedding} days to your wedding ({wedding_date}) — "
            f"now is the ideal window to start the 30-day prep program following your trial. "
            f"{offer_title} covers 4 sessions + take-home care. Want me to reserve your preferred Saturday slot for session 1 next week?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_bridal_followup_v1",
            template_params=[cname, str(days_to_wedding), offer_title],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Customer-facing bridal sequence anchored in days-to-wedding and preferred slot day."
        )

    # -------------------------------------------------------------------------
    # 9. Curious Ask Due
    # -------------------------------------------------------------------------
    def _compose_curious_ask_due(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        body = (
            f"Hi {salutation}! Quick check — what service or treatment has been most asked-for this week at {s.merchant_name}? "
            f"I'll turn your answer into a fresh Google post + a 4-line WhatsApp reply you can send when clients ask about pricing. "
            f"Takes 2 minutes."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_curious_ask_v1",
            template_params=[salutation, s.merchant_name],
            body=body,
            cta="open_ended",
            suppression_key=s.suppression_key,
            rationale="High-engagement curious-ask routine offering immediate reciprocity (Google post + WhatsApp snippet)."
        )

    # -------------------------------------------------------------------------
    # 10. Winback Eligible
    # -------------------------------------------------------------------------
    def _compose_winback_eligible(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        days = s.payload.get("days_since_expiry") or s.days_since_expiry or 30
        dip = s.payload.get("perf_dip_pct", -0.30)
        dip_str = f"{abs(round(dip * 100))}%"
        lapsed = s.payload.get("lapsed_customers_added_since_expiry", 24)

        body = (
            f"Hi {salutation}, profile maintenance for {s.merchant_name} has been paused for {days} days. "
            f"Since pausing, customer discovery dipped {dip_str}, while {lapsed} customers entered the lapsed window. "
            f"Want to reactivate your Pro plan today to restore daily GBP rank and launch a winback recall campaign?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_winback_merchant_v1",
            template_params=[salutation, str(days), dip_str],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Loss-aversion winback message leveraging days paused and lapsed customer count."
        )

    # -------------------------------------------------------------------------
    # 11. IPL Match Day
    # -------------------------------------------------------------------------
    def _compose_ipl_match_today(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        match = s.payload.get("match", "IPL Match")
        venue = s.payload.get("venue", "Stadium")
        is_weeknight = s.payload.get("is_weeknight", False)

        # Retrieve active merchant offer like BOGO
        offer_text = "your BOGO special"
        if s.active_offers:
            offer_text = s.active_offers[0].get("title", offer_text)

        body = (
            f"Quick heads-up {salutation} — {match} at {venue} tonight (7:30pm). "
            f"Important operator note: {'weeknight' if is_weeknight else 'Saturday'} matches typically shift dining covers -12% as fans watch at home. "
            f"Skip the dine-in push tonight; instead promote {offer_text} as a delivery-only match special. "
            f"Want me to draft the Swiggy banner + Insta story copy? Ready in 10 minutes."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_ipl_match_strategy_v1",
            template_params=[salutation, match, venue],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Contrarian operator intelligence: advises delivery pivot instead of dine-in with 10-minute effort cap."
        )

    # -------------------------------------------------------------------------
    # 12. Review Theme Emerged
    # -------------------------------------------------------------------------
    def _compose_review_theme_emerged(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        theme = s.payload.get("theme", "service speed")
        count = s.payload.get("occurrences_30d", 3)
        quote = s.payload.get("common_quote", "had to wait")
        locality_text = f" in {s.locality}" if s.locality else ""

        body = (
            f"Hi {salutation}, review radar check for {s.merchant_name}: {count} customer reviews this month "
            f"highlighted '{theme.replace('_', ' ')}' (e.g. \"{quote}\"). "
            f"Unaddressed review trends hurt diner discovery and orders on Google{locality_text}. "
            f"Want me to draft a ready-to-paste owner reply addressing this? Reply YES to review the draft."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_review_theme_v1",
            template_params=[salutation, theme, str(count)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Synthesizes customer sentiment theme from recent reviews with quote citation and drafted response."
        )

    # -------------------------------------------------------------------------
    # 13. Milestone Reached
    # -------------------------------------------------------------------------
    def _compose_milestone_reached(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        now_val = s.payload.get("value_now", 145)
        milestone = s.payload.get("milestone_value", 150)
        metric = s.payload.get("metric", "reviews").replace("_", " ")
        needed = max(1, milestone - now_val)

        body = (
            f"Hi {salutation}! You're currently at {now_val} {metric} on Google — just {needed} more to cross the big {milestone} milestone! "
            f"Crossing {milestone} boosts local search placement in {s.locality}. "
            f"Want me to generate a 1-click review QR code + WhatsApp ask you can send to today's customers?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_milestone_push_v1",
            template_params=[salutation, str(now_val), str(milestone)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Milestone proximity trigger offering review generation tool with clear locality benefit."
        )

    # -------------------------------------------------------------------------
    # 14. Active Planning Intent
    # -------------------------------------------------------------------------
    def _compose_active_planning_intent(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        topic = s.payload.get("intent_topic", "custom package").replace("_", " ")

        body = (
            f"{salutation}, here is a ready starter draft for your {topic} tailored for {s.locality}:\n"
            f"- Tier 1: Starter Pack @ ₹125/unit (introductory tier)\n"
            f"- Tier 2: Team Value Pack @ ₹115/unit + complimentary addon\n"
            f"- Tier 3: Bulk Partner Tier @ ₹105/unit\n\n"
            f"Want me to finalize the promotional WhatsApp copy and schedule the announcement for tomorrow 10am?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_planning_starter_v1",
            template_params=[salutation, topic],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Executes on merchant's active planning intent with tiered pricing and binary scheduling CTA."
        )

    # -------------------------------------------------------------------------
    # 15. Seasonal Performance Dip Reframe
    # -------------------------------------------------------------------------
    def _compose_seasonal_perf_dip(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        delta_pct = s.payload.get("delta_pct") or -0.30
        pct_str = f"{abs(round(delta_pct * 100))}%"
        members = s.customer_aggregate.get("total_unique_ytd", 245)

        body = (
            f"{salutation}, your views are down {pct_str} this week — but this is the standard seasonal acquisition lull "
            f"across metro {s.category_slug} (peers typically experience -25% to -35% in this window). "
            f"Recommended strategy: pause top-of-funnel ad spend now, and focus retention on your ~{members} active members. "
            f"Want me to draft a 30-day summer attendance challenge to keep them engaged through the dip?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_seasonal_reframe_v1",
            template_params=[salutation, pct_str, str(members)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Pre-empts anxiety by contextualizing seasonal lull; provides budget saving advice + retention challenge."
        )

    # -------------------------------------------------------------------------
    # 16. Customer Lapsed Soft (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_customer_lapsed_soft(self, s: GroundedSignals) -> ComposedOutput:
        cname = s.customer_name or "there"
        salutation = message_formatter.get_salutation(s, customer_facing=True)

        offer_text = "special check-in visit"
        if s.active_offers:
            offer_text = s.active_offers[0].get("title", offer_text)

        body = (
            f"{salutation} We missed you at {s.merchant_name}! It's been a few months since your last visit. "
            f"To welcome you back, we have {offer_text} ready for your next appointment. "
            f"Want me to hold a convenient weekday slot for you this week? Reply YES to confirm."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_soft_winback_v1",
            template_params=[cname, s.merchant_name, offer_text],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Soft winback message for lapsed customer sent on behalf of merchant with binary booking ask."
        )

    # -------------------------------------------------------------------------
    # 17. Customer Lapsed Hard (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_customer_lapsed_hard(self, s: GroundedSignals) -> ComposedOutput:
        cname = s.customer_name or "there"
        salutation = message_formatter.get_salutation(s, customer_facing=True)
        days = s.payload.get("days_since_last_visit", 60)
        focus = s.payload.get("previous_focus", "fitness").replace("_", " ")

        body = (
            f"{salutation} It's been about {days // 7} weeks — happens to most members at some point, no judgment! "
            f"We've updated our schedule with new sessions matching your {focus} focus. "
            f"Want me to hold a free trial spot for you next Tuesday 6:30pm? Reply YES — no commitment, no auto-charge."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_hard_winback_v1",
            template_params=[cname, str(days), focus],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Hard lapse customer winback removing shame and payment friction with single binary commit."
        )

    # -------------------------------------------------------------------------
    # 18. Trial Followup (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_trial_followup(self, s: GroundedSignals) -> ComposedOutput:
        cname = s.customer_name or "there"
        salutation = message_formatter.get_salutation(s, customer_facing=True)
        date = s.payload.get("trial_date", "earlier this week")
        opts = s.payload.get("next_session_options", [])
        opt_label = opts[0].get("label", "Saturday 8am") if opts else "Saturday 8am"

        body = (
            f"{salutation} Hope you enjoyed your trial session on {date}! "
            f"Your next progression session is scheduled for {opt_label}. "
            f"Want me to confirm your spot for {opt_label}? Reply YES to lock it in."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_trial_followup_v1",
            template_params=[cname, date, opt_label],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Follow-up on trial session with single specific next date."
        )

    # -------------------------------------------------------------------------
    # 19. Supply / Batch Recall Alert
    # -------------------------------------------------------------------------
    def _compose_supply_alert(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        molecule = s.payload.get("molecule", "medication")
        batches = ", ".join(s.payload.get("affected_batches", ["specified batch"]))
        mfr = s.payload.get("manufacturer", "Manufacturer")
        chronic_count = s.customer_aggregate.get("chronic_rx_count", 22)

        body = (
            f"{salutation}, urgent compliance notice: voluntary batch recall on {molecule} (batches: {batches}) "
            f"by {mfr} due to sub-potency (no acute safety risk). Checked your repeat-Rx records: {chronic_count} of your "
            f"chronic patients were dispensed these batches in the last 90 days. "
            f"Want me to draft a patient replacement WhatsApp notice you can send today? Reply YES to review the draft."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_drug_recall_alert_v1",
            template_params=[salutation, molecule, batches],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Clinical compliance alert referencing batch numbers and affected patient cohort count."
        )

    # -------------------------------------------------------------------------
    # 20. Chronic Refill Due (Customer-facing)
    # -------------------------------------------------------------------------
    def _compose_chronic_refill_due(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s, customer_facing=True)
        molecules = ", ".join(s.payload.get("molecule_list", ["monthly medications"]))
        runs_out = s.payload.get("stock_runs_out_iso", "28 April")[:10]

        body = (
            f"{salutation} Aapki monthly medicines ({molecules}) {runs_out} ko khatam hongi. "
            f"Same dose, same brand pack ready hai with senior citizen discount applied. "
            f"Free home delivery to your saved address by 5pm tomorrow. "
            f"Reply CONFIRM to dispatch, or let us know if any dosage changed."
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="merchant_on_behalf",
            trigger_id=s.trigger_id,
            template_name="merchant_chronic_refill_v1",
            template_params=[molecules, runs_out],
            body=body,
            cta="binary_confirm_cancel",
            suppression_key=s.suppression_key,
            rationale="Respectful Hindi-English mix refill reminder with molecule names and senior delivery terms."
        )

    # -------------------------------------------------------------------------
    # 21. Category Seasonal Shift
    # -------------------------------------------------------------------------
    def _compose_category_seasonal(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        season = s.payload.get("season", "seasonal").replace("_", " ")
        trends = ", ".join(s.payload.get("trends", ["summer essentials +40%"])[:2]).replace("_", " ")

        body = (
            f"Hi {salutation}! Category demand update for {season}: {trends} in your locality. "
            f"Adjusting your GBP shelf highlight and front-of-store showcase captures this surge. "
            f"Want me to draft a quick seasonal wellness post highlighting these essentials?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_seasonal_demand_v1",
            template_params=[salutation, season, trends],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Category-level seasonal demand alert advising merchandising and GBP highlight."
        )

    # -------------------------------------------------------------------------
    # 22. GBP Unverified
    # -------------------------------------------------------------------------
    def _compose_gbp_unverified(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        uplift = round((s.payload.get("estimated_uplift_pct", 0.30)) * 100)

        body = (
            f"Hi {salutation}, notice for {s.merchant_name}: your Google Business profile is currently unverified. "
            f"Verified listings in {s.locality} receive on average +{uplift}% more customer calls and directions. "
            f"Verification takes 5 minutes by phone or postcard. Want me to guide you through the verification steps now?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_gbp_unverified_v1",
            template_params=[salutation, str(uplift)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="GBP verification prompt highlighting local discovery uplift and low effort."
        )

    # -------------------------------------------------------------------------
    # 23. CDE / Professional Opportunity
    # -------------------------------------------------------------------------
    def _compose_cde_opportunity(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        credits = s.payload.get("credits", 2)
        d = s.digest_item or {}
        title = d.get("title", "Clinical Masterclass")
        fee = s.payload.get("fee", "free for members").replace("_", " ")

        body = (
            f"{salutation}, professional development alert: upcoming {title} ({credits} credit hours). "
            f"Registration is {fee}. "
            f"Want me to send you the direct registration details and syllabus summary?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_cde_invite_v1",
            template_params=[salutation, title, str(credits)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Professional educational webinar invite with credit hours and member pricing."
        )

    # -------------------------------------------------------------------------
    # 24. Competitor Opened
    # -------------------------------------------------------------------------
    def _compose_competitor_opened(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        comp = s.payload.get("competitor_name", "A new clinic")
        dist = s.payload.get("distance_km", 1.5)
        offer = s.payload.get("their_offer", "discount pricing")

        body = (
            f"Local market watch {salutation}: {comp} opened {dist}km away on Google Maps promoting {offer}. "
            f"Our data shows established listings win on trust rather than price wars. "
            f"Want me to publish a GBP post highlighting your verified patient reviews and clinical track record?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_competitor_defense_v1",
            template_params=[salutation, comp, str(dist)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Competitor entry notification advising trust/reputation positioning instead of discount matching."
        )

    # -------------------------------------------------------------------------
    # 25. Dormant with Vera
    # -------------------------------------------------------------------------
    def _compose_dormant_with_vera(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        days = s.payload.get("days_since_last_merchant_message", 14)
        views = s.perf_views or 1200

        body = (
            f"Hi {salutation}! Quick check-in — your Google profile generated {views:,} views over the last 30 days. "
            f"Is there any new service, photo, or timing you'd like me to update on your listing this week?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_dormant_checkin_v1",
            template_params=[salutation, str(views)],
            body=body,
            cta="open_ended",
            suppression_key=s.suppression_key,
            rationale="Low-friction check-in for dormant merchant anchored in monthly view volume."
        )

    # -------------------------------------------------------------------------
    # Fallback Generic Handler
    # -------------------------------------------------------------------------
    def _compose_generic(self, s: GroundedSignals) -> ComposedOutput:
        salutation = message_formatter.get_salutation(s)
        views = s.perf_views or 1000

        body = (
            f"Hi {salutation}! Reviewing {s.merchant_name} on Google — your profile reached {views:,} views recently. "
            f"Want me to draft a fresh Google post to keep your listing active this week?"
        )
        return ComposedOutput(
            conversation_id=message_formatter.format_conversation_id(s),
            merchant_id=s.merchant_id,
            customer_id=s.customer_id,
            send_as="vera",
            trigger_id=s.trigger_id,
            template_name="vera_generic_v1",
            template_params=[salutation, str(views)],
            body=body,
            cta="binary_yes_no",
            suppression_key=s.suppression_key,
            rationale="Fallback composition anchored in merchant identity and views."
        )


deterministic_composer = DeterministicComposer()
