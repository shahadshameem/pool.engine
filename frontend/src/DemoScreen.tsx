import { useState } from 'react'
import { MobileShell } from './components/layout/MobileShell'
import { Button } from './components/ui/button'
import { Input } from './components/ui/input'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './components/ui/card'
import { Modal } from './components/ui/modal'
import { useToast } from './components/feedback/ToastContext'
import { EmptyState } from './components/feedback/EmptyState'
import { ErrorState } from './components/feedback/ErrorState'
import { DateTimeFields } from './components/common/DateTimeFields'
import { getLocalDateString } from './utils/formatters'
import { MapPin, Search } from 'lucide-react'

export function DemoScreen() {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [demoDate, setDemoDate] = useState(getLocalDateString())
  const [demoTime, setDemoTime] = useState("")
  const { showToast } = useToast()

  return (
    <MobileShell>
      <div className="flex flex-col gap-8 px-4 py-6">

        {/* Header / Typography */}
        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <img src="/logo.png" alt="WayMate" className="h-8 w-8 object-contain" />
            <h1 className="text-2xl font-black">WayMate Design System</h1>
          </div>
          <p className="text-sm text-muted-foreground">Mobile-first MVP foundation testing.</p>
        </section>

        {/* Buttons */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold">Buttons</h2>
          <div className="flex flex-wrap gap-3">
            <Button className="w-full">Primary Action</Button>
            <Button variant="secondary" className="w-full">Secondary</Button>
            <Button variant="outline" className="flex-1">Outline</Button>
            <Button variant="ghost" className="flex-1">Ghost</Button>
            <Button variant="destructive" className="w-full">Destructive</Button>
            <Button isLoading className="w-full">Loading State</Button>
          </div>
        </section>

        {/* Inputs & Pickers */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold">Inputs & Date/Time Fields</h2>
          <Input label="Starting Location" placeholder="e.g. CET Campus" />
          <Input label="Destination" placeholder="e.g. Trivandrum" helperText="Enter your home city." />
          <div className="pt-2">
            <h3 className="text-sm font-semibold mb-2 text-muted-foreground">Standard 2-Field Date & Time Picker</h3>
            <DateTimeFields
              date={demoDate}
              time={demoTime}
              onDateChange={setDemoDate}
              onTimeChange={setDemoTime}
            />
          </div>
        </section>

        {/* Cards */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold">Cards</h2>
          <Card>
            <CardHeader>
              <CardTitle>Upcoming Ride</CardTitle>
              <CardDescription>Friday, 4:00 PM</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2 text-sm">
                <MapPin className="h-4 w-4 text-primary" />
                <span>CET → Ernakulam</span>
              </div>
            </CardContent>
            <CardFooter>
              <Button size="sm" className="w-full">View Details</Button>
            </CardFooter>
          </Card>
        </section>

        {/* Modals & Toasts */}
        <section className="space-y-4">
          <h2 className="text-lg font-bold">Feedback / Overlays</h2>
          <div className="grid grid-cols-2 gap-3">
            <Button onClick={() => setIsModalOpen(true)} variant="outline">Open Modal</Button>
            <Button onClick={() => showToast('Ride request sent!', 'success')} variant="outline">Success Toast</Button>
            <Button onClick={() => showToast('Could not load rides.', 'error')} variant="outline">Error Toast</Button>
            <Button onClick={() => showToast('New ride available matching your route.', 'warning')} variant="outline">Warning Toast</Button>
          </div>
        </section>

        {/* Empty State */}
        <section className="space-y-4 rounded-xl border border-dashed p-4">
          <EmptyState
            icon={<Search className="h-8 w-8" />}
            title="No rides found"
            description="There are currently no rides available for this route."
            actionLabel="Offer a Ride"
            onAction={() => showToast('Navigate to offer ride')}
          />
        </section>

        {/* Error State */}
        <section className="space-y-4 rounded-xl border border-dashed p-4">
          <ErrorState isInline message="Could not connect to the network." onRetry={() => {}} />
        </section>

      </div>

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title="Confirm Request">
        <div className="space-y-4 pt-4">
          <p className="text-sm text-muted-foreground">Are you sure you want to request a seat for this ride? The host will be notified.</p>
          <div className="flex gap-3 pt-4">
            <Button variant="outline" className="flex-1" onClick={() => setIsModalOpen(false)}>Cancel</Button>
            <Button className="flex-1" onClick={() => {
              setIsModalOpen(false);
              showToast('Request sent successfully!', 'success');
            }}>Confirm</Button>
          </div>
        </div>
      </Modal>

    </MobileShell>
  )
}
