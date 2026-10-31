/**
 * Privacy Notice Page — WayMate
 *
 * ⚠️ LEGAL REVIEW REQUIRED (entire page):
 *   All sections marked [LAWYER REVIEW] must be reviewed and approved by
 *   qualified legal counsel familiar with DPDPA 2023 before public release.
 *   In particular:
 *     - Retention periods (currently indicative)
 *     - Third-party data processor agreements
 *     - Grievance officer details (currently placeholder)
 *     - Basis for international data transfer (Firebase servers may be outside India)
 *     - Children's data section (if app serves <18-year-olds)
 *
 * Implements: DPDPA 2023 §5 (notice), §6 (consent), §9 (children), §12-14 (rights)
 */
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Shield, Database, Clock, Globe, Users, Mail } from "lucide-react"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { GRIEVANCE_OFFICER } from "../services/consent/dataRightsService"

interface SectionProps {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
  lawyerReview?: boolean
}

function Section({ icon, title, children, lawyerReview }: SectionProps) {
  return (
    <div className="bg-card rounded-[20px] border border-border/60 shadow-sm p-5 space-y-3">
      <div className="flex items-center space-x-3">
        <div className="p-2 bg-secondary rounded-xl text-foreground shrink-0">
          {icon}
        </div>
        <h3 className="text-[15px] font-extrabold text-foreground">{title}</h3>
        {lawyerReview && (
          <span className="ml-auto shrink-0 text-[10px] font-bold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded-full border border-amber-300/60">
            ⚠️ Lawyer Review
          </span>
        )}
      </div>
      <div className="text-[12px] text-muted-foreground leading-relaxed space-y-2">
        {children}
      </div>
    </div>
  )
}

export function PrivacyNoticePage() {
  const navigate = useNavigate()

  return (
    <MobileShell hideBottomNav hasStickyHeader className="bg-background min-h-screen">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between bg-background/95 px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 backdrop-blur border-b border-border/40">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate(-1)}
          className="-ml-2 h-9 w-9 rounded-full"
        >
          <ArrowLeft className="h-5 w-5 text-foreground" />
        </Button>
        <h1 className="text-[17px] font-bold text-foreground">Privacy Notice</h1>
        <div className="w-9" />
      </div>

      <div className="p-5 space-y-4">
        {/* Hero */}
        <div className="bg-card rounded-[24px] border border-border/60 p-6 shadow-sm space-y-3">
          <div className="h-12 w-12 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
            <Shield className="h-6 w-6 text-foreground" />
          </div>
          <div className="space-y-1">
            <h2 className="text-[18px] font-extrabold text-foreground">
              WayMate Privacy Notice
            </h2>
            {/* ⚠️ LAWYER REVIEW: Effective date and version must be updated on every material change */}
            <p className="text-[11px] text-muted-foreground">
              Effective: <strong>September 28, 2026</strong> · Version 1.0.0-dpdp
            </p>
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              This notice explains how WayMate ("we", "our", "us") collects,
              uses, stores, and shares your personal data, and how you can
              exercise your rights under the Digital Personal Data Protection
              Act 2023 (India).
            </p>
          </div>
        </div>

        {/* 1. Data we collect */}
        <Section icon={<Database className="h-4 w-4" />} title="1. Data We Collect" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: Verify this list is exhaustive and accurate */}
          <table className="w-full text-left border-collapse text-[11px]">
            <thead>
              <tr className="border-b border-border/40">
                <th className="pb-1.5 font-bold text-foreground w-[40%]">Data</th>
                <th className="pb-1.5 font-bold text-foreground">Purpose</th>
              </tr>
            </thead>
            <tbody className="space-y-2">
              {[
                ["Full name", "Display in ride listings; safety"],
                ["Email address", "Account login; verification"],
                ["Mobile phone number", "Contact after ride acceptance only"],
                ["College, department, year", "Ride-matching; verification"],
                ["Hostel / locality (text)", "Ride-discovery; no GPS stored"],
                ["Gender", "Safety: same-gender ride matching"],
                ["Ride origin & destination", "Ride-matching; history"],
                ["Device token (FCM)", "Push notifications"],
                ["Firebase Analytics events", "Crash & performance analytics (optional)"],
                ["IP address (Firebase)", "Security; fraud prevention (Firebase-managed)"],
                ["Consent records", "DPDPA audit trail"],
              ].map(([data, purpose]) => (
                <tr key={data} className="border-b border-border/20">
                  <td className="py-1.5 font-medium text-foreground pr-2">{data}</td>
                  <td className="py-1.5">{purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {/* 2. Why we process your data */}
        <Section icon={<Users className="h-4 w-4" />} title="2. Why We Process Your Data" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: Legal bases must be verified under DPDPA §4 */}
          <p>
            We process your personal data under the following lawful bases:
          </p>
          <ul className="list-disc list-inside space-y-1">
            <li>
              <strong>Contract performance:</strong> name, email, college, ride
              data — needed to provide the carpooling service.
            </li>
            <li>
              <strong>Explicit consent:</strong> phone number sharing, analytics,
              push notifications, and hostel / stay location. You may withdraw at any time.
            </li>
            <li>
              <strong>Legitimate interest:</strong> security logging, fraud
              prevention, and abuse detection — subject to your right to object.
            </li>
          </ul>
        </Section>

        {/* 3. Retention */}
        <Section icon={<Clock className="h-4 w-4" />} title="3. Retention Periods" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: These retention periods are indicative and must be confirmed */}
          <ul className="list-disc list-inside space-y-1">
            <li><strong>Active account data:</strong> Retained while account is active.</li>
            <li><strong>Ride history (anonymised):</strong> Up to 2 years for safety purposes.</li>
            <li><strong>Consent records:</strong> 5 years after account deletion (audit requirement).</li>
            <li><strong>Data-rights request records:</strong> 3 years.</li>
            <li><strong>Analytics events:</strong> 14 months (Firebase default).</li>
            <li>
              <strong>Account deletion:</strong> Profile and personal data deleted within
              30 days of account-deletion request. Anonymised ride records retained for safety.
            </li>
          </ul>
        </Section>

        {/* 4. Third parties */}
        <Section icon={<Globe className="h-4 w-4" />} title="4. Third-Party Services" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: Verify DPAs with each processor; confirm cross-border transfer mechanism */}
          <p>
            We use the following sub-processors. Data may be transferred to
            servers outside India:
          </p>
          <ul className="list-disc list-inside space-y-1.5">
            <li>
              <strong>Google Firebase</strong> (Authentication, Firestore, Cloud
              Messaging, Analytics) — Google LLC, USA. Governed by Google's Data
              Processing Agreement.
            </li>
            <li>
              <strong>Google Analytics (Firebase)</strong> — used only with your
              explicit consent.
            </li>
          </ul>
          <p className="mt-1">
            We do <strong>not</strong> sell personal data to third parties for
            advertising. We do <strong>not</strong> use any advertising-network trackers.
          </p>
        </Section>

        {/* 5. Your Rights */}
        <Section icon={<Shield className="h-4 w-4" />} title="5. Your Rights (DPDPA §12–14)">
          <ul className="list-disc list-inside space-y-1">
            <li><strong>Access:</strong> Request a summary of data we hold (§12).</li>
            <li><strong>Correction:</strong> Ask us to fix inaccurate data (§13(1)).</li>
            <li><strong>Erasure:</strong> Delete your account and data (§13(2)).</li>
            <li><strong>Withdrawal:</strong> Withdraw consent for optional processing at any time (§14).</li>
            <li><strong>Grievance:</strong> File a complaint with our Grievance Officer (§13(3)).</li>
            <li><strong>Nomination:</strong> Nominate a representative (§14(4)).</li>
          </ul>
          <p className="mt-1">
            Exercise your rights via{" "}
            <button
              onClick={() => navigate("/data-rights")}
              className="underline font-semibold text-foreground"
            >
              Profile → Data Rights Request
            </button>
            .
          </p>
        </Section>

        {/* 6. Grievance Officer */}
        <Section icon={<Mail className="h-4 w-4" />} title="6. Grievance Officer" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: Officer name and contact must be a real, designated individual */}
          <p>
            For privacy concerns or complaints, contact our Grievance Officer:
          </p>
          <div className="mt-1 space-y-0.5">
            <p><strong>{GRIEVANCE_OFFICER.name}</strong></p>
            <p>Email: <a href={`mailto:${GRIEVANCE_OFFICER.email}`} className="underline">{GRIEVANCE_OFFICER.email}</a></p>
            <p>{GRIEVANCE_OFFICER.address}</p>
            <p>Response time: within {GRIEVANCE_OFFICER.responseTimeDays} days.</p>
          </div>
          <p className="mt-1.5">
            If unresolved, you may escalate to the{" "}
            <strong>Data Protection Board of India</strong> (dpboard.gov.in).
          </p>
        </Section>

        {/* 7. Changes */}
        <Section icon={<Clock className="h-4 w-4" />} title="7. Changes to This Notice" lawyerReview>
          {/* ⚠️ LAWYER REVIEW: Notification mechanism and re-consent triggers must be confirmed */}
          <p>
            We may update this notice from time to time. Material changes will
            be communicated via in-app notification and/or email at least 7 days
            before taking effect. Continued use after the effective date
            constitutes acknowledgment (not fresh consent for new purposes — new
            purposes require fresh opt-in).
          </p>
        </Section>

        {/* Data Rights CTA */}
        <Button
          variant="primary"
          size="lg"
          className="w-full"
          onClick={() => navigate("/data-rights")}
        >
          Submit a Data Rights Request
        </Button>

        {/* Footer contact */}
        <div className="text-center space-y-1 pt-2">
          <p className="text-[11px] text-muted-foreground">
            Grievance Officer:{" "}
            <a
              href={`mailto:${GRIEVANCE_OFFICER.email}`}
              className="underline font-semibold text-foreground"
            >
              {GRIEVANCE_OFFICER.email}
            </a>
          </p>
          <p className="text-[10px] text-muted-foreground/70">
            ⚠️ Legal copy — for lawyer review before go-live
          </p>
        </div>
      </div>
    </MobileShell>
  )
}
