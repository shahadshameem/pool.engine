/**
 * Terms of Service Page — WayMate
 *
 * ⚠️ LEGAL REVIEW REQUIRED (entire document):
 *   All sections — especially the Data Protection Clause and liability
 *   limitations — must be reviewed and approved by qualified legal counsel
 *   before publication to end users.
 *
 * Includes DPDPA 2023-required Data Protection clause per §5 notice obligations.
 */
import { useNavigate } from "react-router-dom"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { ArrowLeft, FileText } from "lucide-react"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { GRIEVANCE_OFFICER } from "../services/consent/dataRightsService"
import { useSEO } from "../hooks/useSEO"

interface ClauseProps {
  number: string
  title: string
  children: React.ReactNode
  lawyerReview?: boolean
}

function Clause({ number, title, children, lawyerReview }: ClauseProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center space-x-2">
        <h3 className="text-[14px] font-extrabold text-foreground">
          {number}. {title}
        </h3>
        {lawyerReview && (
          <span className="text-[9px] font-bold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded-full border border-amber-300/60 shrink-0">
            ⚠️ Lawyer Review
          </span>
        )}
      </div>
      <div className="text-[12px] text-muted-foreground leading-relaxed space-y-1.5">
        {children}
      </div>
    </div>
  )
}

export function TermsPage() {
  useSEO({
    title: "Terms of Service & DPDPA Notice",
    description: "Terms of Service and Data Protection notice for WayMate (wmate.app) college ridesharing and carpool community.",
    canonicalPath: "/terms",
  })

  const navigate = useNavigate()
  const { goBack } = useBackNavigation()

  return (
    <MobileShell hideBottomNav hasStickyHeader className="bg-background min-h-screen">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between bg-background/95 px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 backdrop-blur border-b border-border/40">
        <Button
          variant="ghost"
          size="icon"
          onClick={goBack}
          className="-ml-2 h-9 w-9 rounded-full"
        >
          <ArrowLeft className="h-5 w-5 text-foreground" />
        </Button>
        <h1 className="text-[17px] font-bold text-foreground">Terms of Service</h1>
        <div className="w-9" />
      </div>

      <div className="p-5 space-y-5">
        {/* Hero */}
        <div className="bg-card rounded-[24px] border border-border/60 p-5 shadow-sm space-y-2">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-secondary rounded-xl shrink-0">
              <FileText className="h-5 w-5 text-foreground" />
            </div>
            <div>
              <h2 className="text-[17px] font-extrabold text-foreground">
                WayMate Terms of Service
              </h2>
              {/* ⚠️ LAWYER REVIEW: Update effective date on every material change */}
              <p className="text-[11px] text-muted-foreground">
                Effective: September 28, 2026 · Version 1.0.0
              </p>
            </div>
          </div>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            By using WayMate you agree to these Terms. Please read them carefully.
            {/* ⚠️ LAWYER REVIEW: Confirm this constitutes a binding agreement under Indian contract law */}
          </p>
        </div>

        <div className="bg-card rounded-[20px] border border-border/60 p-5 shadow-sm space-y-5">
          <Clause number="1" title="The Service" lawyerReview>
            <p>
              WayMate is an exclusive peer-to-peer campus carpooling and ride-sharing platform for verified
              college students in India. We connect student ride hosts with student co-riders
              traveling along the same route to promote safe, collaborative student travel.
              WayMate is a student connecting platform and does not operate any commercial transport service.
            </p>
          </Clause>

          <Clause number="2" title="Eligibility">
            <p>
              You must be a currently enrolled student at a partner institution and
              must be at least 18 years of age to use WayMate.
              {/* ⚠️ LAWYER REVIEW: If minors are permitted under parental consent, add DPDPA §9 provisions */}
            </p>
          </Clause>

          <Clause number="3" title="Account Responsibilities">
            <p>
              You are responsible for maintaining the confidentiality of your
              credentials and for all activity that occurs under your account.
              Sharing your account is prohibited.
            </p>
          </Clause>

          <Clause number="4" title="Safety Rules">
            <p>
              All users must behave respectfully and safely. Misrepresentation of
              identity, threatening behaviour, or any activity that endangers other
              users is grounds for immediate account termination and, where
              applicable, law enforcement notification.
            </p>
          </Clause>

          <Clause number="5" title="Prohibited Conduct">
            <p>You may not use WayMate to:</p>
            <ul className="list-disc list-inside space-y-0.5 pl-1">
              <li>Impersonate any person or entity</li>
              <li>Collect data about other users beyond what is needed for your ride</li>
              <li>Engage in commercial transport (fare-charging) without proper licences</li>
              <li>Harass, abuse, or harm other users</li>
              <li>Circumvent security or access controls</li>
            </ul>
          </Clause>

          {/* ================================================================
              DATA PROTECTION CLAUSE — DPDPA 2023
              ⚠️ LAWYER REVIEW REQUIRED: This clause must be verified by
              qualified legal counsel before public release.
              ================================================================ */}
          <div className="border-t border-border/40 pt-5">
            <div className="mb-1.5 flex items-center space-x-2">
              <span className="text-[10px] font-bold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded-full border border-amber-300/60">
                ⚠️ Lawyer Review — Data Protection Clause
              </span>
            </div>
          </div>

          <Clause number="6" title="Data Protection (DPDPA 2023)" lawyerReview>
            <p>
              WayMate processes personal data as a <strong>Data Fiduciary</strong>{" "}
              under the Digital Personal Data Protection Act 2023 (DPDPA), India.
            </p>
            <p className="font-semibold text-foreground mt-1">6.1 Collection</p>
            <p>
              We collect only the personal data necessary to provide the
              carpooling service (name, email, phone, college details, ride
              origin/destination, home locality). Full details are in our{" "}
              <button
                onClick={() => navigate("/profile/privacy")}
                className="underline text-foreground font-semibold"
              >
                Privacy Notice
              </button>
              .
            </p>
            <p className="font-semibold text-foreground mt-1">6.2 Consent</p>
            <p>
              We process non-essential data only with your free, specific,
              informed, and unambiguous consent (DPDPA §6). You may withdraw
              consent at any time via Profile → Privacy Settings or by submitting
              a{" "}
              <button
                onClick={() => navigate("/data-rights")}
                className="underline text-foreground font-semibold"
              >
                Data Rights Request
              </button>
              .
            </p>
            <p className="font-semibold text-foreground mt-1">6.3 Your Rights</p>
            <p>
              You have the right to access, correct, erase your data, and to
              nominate a representative, as provided under DPDPA §12–14. Submit
              requests at Profile → Data Rights Request or email{" "}
              <a
                href={`mailto:${GRIEVANCE_OFFICER.email}`}
                className="underline text-foreground"
              >
                {GRIEVANCE_OFFICER.email}
              </a>
              .
            </p>
            <p className="font-semibold text-foreground mt-1">6.4 Security</p>
            <p>
              We implement reasonable technical and organisational security
              measures. In the event of a personal data breach, we will notify
              the Data Protection Board of India within 72 hours (DPDPA §8(6))
              and notify affected users as required by law.
              {/* ⚠️ LAWYER REVIEW: Confirm breach notification obligations and timelines */}
            </p>
            <p className="font-semibold text-foreground mt-1">6.5 Grievance Officer</p>
            <p>
              Our Grievance Officer for data-related complaints is reachable at{" "}
              <a
                href={`mailto:${GRIEVANCE_OFFICER.email}`}
                className="underline text-foreground"
              >
                {GRIEVANCE_OFFICER.email}
              </a>{" "}
              and will respond within {GRIEVANCE_OFFICER.responseTimeDays} days. Unresolved
              grievances may be escalated to the Data Protection Board of India
              (dpboard.gov.in).
            </p>
          </Clause>

          <Clause number="7" title="Disclaimer of Warranties" lawyerReview>
            <p>
              WayMate is provided "as is". We do not guarantee the safety,
              reliability, or continuity of rides arranged via the platform. Users
              engage in carpooling at their own risk.
              {/* ⚠️ LAWYER REVIEW: Verify this limitation is enforceable under Indian consumer protection law */}
            </p>
          </Clause>

          <Clause number="8" title="Governing Law" lawyerReview>
            <p>
              These Terms are governed by the laws of India. Disputes shall be
              subject to the exclusive jurisdiction of courts in Trivandrum,
              Kerala, India.
              {/* ⚠️ LAWYER REVIEW: Confirm jurisdiction clause and arbitration requirements */}
            </p>
          </Clause>

          <Clause number="9" title="Contact">
            <p>
              For any questions about these Terms, contact us at{" "}
              <a
                href={`mailto:${GRIEVANCE_OFFICER.email}`}
                className="underline text-foreground font-semibold"
              >
                {GRIEVANCE_OFFICER.email}
              </a>
              .
            </p>
          </Clause>
        </div>

        <p className="text-center text-[10px] text-muted-foreground/70 pb-2">
          ⚠️ This document is a draft pending qualified legal review before public release.
        </p>
      </div>
    </MobileShell>
  )
}
