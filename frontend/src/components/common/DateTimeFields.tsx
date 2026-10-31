import { useState, useEffect } from "react"
import { createPortal } from "react-dom"
import { Calendar as CalendarIcon, Clock, ChevronDown, ChevronLeft, ChevronRight, X, Users } from "lucide-react"
import { formatDateShort, formatTime12h, getLocalDateString } from "../../utils/formatters"
import { cn } from "../../lib/utils"

export interface DateTimeFieldsProps {
  date: string // YYYY-MM-DD or ""
  time: string // HH:mm or ""
  onDateChange: (date: string) => void
  onTimeChange: (time: string) => void
  seats?: number
  onSeatsChange?: (seats: number) => void
  dateError?: string
  timeError?: string
  minDate?: string
  className?: string
}

export function DateTimeFields({
  date,
  time,
  onDateChange,
  onTimeChange,
  seats,
  onSeatsChange,
  dateError,
  timeError,
  minDate: _minDate,
  className = ""
}: DateTimeFieldsProps) {
  const [openPicker, setOpenPicker] = useState<"date" | "time" | null>(null)

  const todayObj = new Date()
  const todayStr = getLocalDateString(todayObj)
  const effectiveMinDate = _minDate || todayStr
  const todayYear = todayObj.getFullYear()
  const todayMonth = todayObj.getMonth()

  // Calendar Month State
  const initialDateObj = date ? new Date(date + "T00:00:00") : new Date()
  const [currentYear, setCurrentYear] = useState(initialDateObj.getFullYear())
  const [currentMonth, setCurrentMonth] = useState(initialDateObj.getMonth())

  // Check if a given HH:mm time string is in the past for the currently selected date
  const isTimeInPast = (timeVal: string) => {
    if (!timeVal) return false
    const targetDate = date || todayStr
    if (targetDate > todayStr) return false
    if (targetDate < todayStr) return true

    const parts = timeVal.split(":")
    const slotMins = parseInt(parts[0], 10) * 60 + parseInt(parts[1] || "0", 10)
    const now = new Date()
    const currentMins = now.getHours() * 60 + now.getMinutes()
    return slotMins < currentMins
  }

  // Time Picker State (defaults to next upcoming 15-minute slot today)
  const getInitialTimeParts = (t: string) => {
    if (t && !isTimeInPast(t)) {
      const parts = t.split(":")
      let h = parseInt(parts[0], 10)
      const m = parts[1] || "00"
      const ampm = h >= 12 ? "PM" : "AM"
      h = h % 12
      if (h === 0) h = 12
      return { hour: h < 10 ? `0${h}` : `${h}`, minute: m, ampm }
    }

    const now = new Date()
    const currentH = now.getHours()
    const currentM = now.getMinutes()
    let nextM = Math.ceil((currentM + 1) / 15) * 15
    let nextH = currentH
    if (nextM >= 60) {
      nextM = 0
      nextH = (nextH + 1) % 24
    }
    const ampm = nextH >= 12 ? "PM" : "AM"
    let displayH = nextH % 12
    if (displayH === 0) displayH = 12
    return {
      hour: displayH < 10 ? `0${displayH}` : `${displayH}`,
      minute: nextM < 10 ? `0${nextM}` : `${nextM}`,
      ampm
    }
  }

  const [selectedHour, setSelectedHour] = useState("09")
  const [selectedMinute, setSelectedMinute] = useState("00")
  const [selectedAmPm, setSelectedAmPm] = useState("AM")

  useEffect(() => {
    const parts = getInitialTimeParts(time)
    setSelectedHour(parts.hour)
    setSelectedMinute(parts.minute)
    setSelectedAmPm(parts.ampm)

    if (time && isTimeInPast(time)) {
      onTimeChange("")
    }
  }, [time, date, openPicker])

  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ]
  const daysOfWeek = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]

  const isPrevMonthDisabled = currentYear < todayYear || (currentYear === todayYear && currentMonth <= todayMonth)

  const handlePrevMonth = () => {
    if (isPrevMonthDisabled) return
    if (currentMonth === 0) {
      setCurrentMonth(11)
      setCurrentYear(prev => prev - 1)
    } else {
      setCurrentMonth(prev => prev - 1)
    }
  }

  const handleNextMonth = () => {
    if (currentMonth === 11) {
      setCurrentMonth(0)
      setCurrentYear(prev => prev + 1)
    } else {
      setCurrentMonth(prev => prev + 1)
    }
  }

  const getDaysInMonth = (year: number, month: number) => new Date(year, month + 1, 0).getDate()
  const getFirstDayOfMonth = (year: number, month: number) => new Date(year, month, 1).getDay()

  const daysInMonth = getDaysInMonth(currentYear, currentMonth)
  const firstDay = getFirstDayOfMonth(currentYear, currentMonth)

  const calendarCells = []
  for (let i = 0; i < firstDay; i++) {
    calendarCells.push(null)
  }
  for (let d = 1; d <= daysInMonth; d++) {
    calendarCells.push(d)
  }

  const handleSelectDay = (day: number) => {
    const formattedMonth = currentMonth + 1 < 10 ? `0${currentMonth + 1}` : `${currentMonth + 1}`
    const formattedDay = day < 10 ? `0${day}` : `${day}`
    const selectedDateStr = `${currentYear}-${formattedMonth}-${formattedDay}`
    onDateChange(selectedDateStr)
    setOpenPicker(null)
  }

  const handleClearDate = () => {
    onDateChange("")
    setOpenPicker(null)
  }

  let customH = parseInt(selectedHour, 10)
  if (selectedAmPm === "PM" && customH < 12) customH += 12
  if (selectedAmPm === "AM" && customH === 12) customH = 0
  const formattedCustomH = customH < 10 ? `0${customH}` : `${customH}`
  const customTimeVal = `${formattedCustomH}:${selectedMinute}`
  const isCustomTimePast = isTimeInPast(customTimeVal)

  const handleConfirmCustomTime = () => {
    if (isCustomTimePast) return
    onTimeChange(customTimeVal)
    setOpenPicker(null)
  }

  const handleClearTime = () => {
    onTimeChange("")
    setOpenPicker(null)
  }

  const dateDisplay = date ? formatDateShort(date) : "Select date"
  const timeDisplay = time ? formatTime12h(time) : "Select time"

  const HOURS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
  const MINUTES = ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"]

  const get24HourTimeStr = (hStr: string, mStr: string, period: string) => {
    let h = parseInt(hStr, 10)
    if (period === "PM" && h < 12) h += 12
    if (period === "AM" && h === 12) h = 0
    const formattedH = h < 10 ? `0${h}` : `${h}`
    return `${formattedH}:${mStr}`
  }

  const isHourPast = (hStr: string) => {
    return isTimeInPast(get24HourTimeStr(hStr, "55", selectedAmPm))
  }

  const isMinutePast = (mStr: string) => {
    return isTimeInPast(get24HourTimeStr(selectedHour, mStr, selectedAmPm))
  }

  return (
    <div className={cn("w-full space-y-3", className)}>
      <div className="grid grid-cols-2 gap-2 min-[360px]:gap-2.5 w-full">

        {/* DATE FIELD */}
        <div className="space-y-1 flex-1 min-w-0">
          <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">
            DATE
          </label>
          <button
            type="button"
            onClick={() => setOpenPicker(openPicker === "date" ? null : "date")}
            className={cn(
              "w-full h-14 bg-muted border rounded-[16px] px-2 min-[360px]:px-2.5 sm:px-3 flex items-center justify-between transition-transform transition-colors duration-150 hover:bg-muted/80 active:scale-[0.98] cursor-pointer",
              dateError ? "border-destructive text-destructive" : "border-border/40",
              openPicker === "date" ? "border-foreground ring-2 ring-foreground/10" : ""
            )}
          >
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <CalendarIcon className="h-4 w-4 text-foreground shrink-0" strokeWidth={1.8} />
              <span className={cn(
                "text-[11.5px] min-[360px]:text-[12.5px] sm:text-[14px] font-semibold tracking-tight truncate leading-tight tabular-nums",
                date ? "text-foreground" : "text-muted-foreground"
              )}>
                {dateDisplay}
              </span>
            </div>
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          </button>
          {dateError && <p className="text-[11px] font-medium text-destructive px-1">{dateError}</p>}
        </div>

        {/* TIME FIELD */}
        <div className="space-y-1 flex-1 min-w-0">
          <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">
            TIME
          </label>
          <button
            type="button"
            onClick={() => setOpenPicker(openPicker === "time" ? null : "time")}
            className={cn(
              "w-full h-14 bg-muted border rounded-[16px] px-2 min-[360px]:px-2.5 sm:px-3 flex items-center justify-between transition-transform transition-colors duration-150 hover:bg-muted/80 active:scale-[0.98] cursor-pointer",
              timeError ? "border-destructive text-destructive" : "border-border/40",
              openPicker === "time" ? "border-foreground ring-2 ring-foreground/10" : ""
            )}
          >
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <Clock className="h-4 w-4 text-foreground shrink-0" strokeWidth={1.8} />
              <span className={cn(
                "text-[11.5px] min-[360px]:text-[12.5px] sm:text-[14px] font-semibold tracking-tight truncate leading-tight tabular-nums",
                time ? "text-foreground" : "text-muted-foreground"
              )}>
                {timeDisplay}
              </span>
            </div>
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          </button>
          {timeError && <p className="text-[11px] font-medium text-destructive px-1">{timeError}</p>}
        </div>

      </div>

      {/* SEATS FIELD (if onSeatsChange provided) */}
      {onSeatsChange && (
        <div className="space-y-1 w-full">
          <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">
            SEATS
          </label>
          <div className="w-full h-14 bg-muted border border-border/40 rounded-[16px] px-3.5 flex items-center justify-between transition-all">
            <div className="flex items-center space-x-2.5 min-w-0">
              <Users className="h-4.5 w-4.5 text-foreground shrink-0" strokeWidth={1.8} />
              <span className="text-[13px] sm:text-[14px] font-semibold text-foreground">
                {(seats || 1)} {(seats || 1) === 1 ? "seat" : "seats"} needed
              </span>
            </div>
            <div className="flex items-center space-x-2 bg-card border border-border/60 rounded-full p-1 shadow-2xs">
              <button
                type="button"
                onClick={() => onSeatsChange(Math.max(1, (seats || 1) - 1))}
                disabled={(seats || 1) <= 1}
                className="h-7 w-7 rounded-full bg-muted hover:bg-muted/80 flex items-center justify-center font-bold text-[14px] text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                aria-label="Decrease seats"
              >
                -
              </button>
              <span className="text-[14px] font-extrabold text-foreground w-4 text-center tabular-nums">
                {seats || 1}
              </span>
              <button
                type="button"
                onClick={() => onSeatsChange(Math.min(6, (seats || 1) + 1))}
                disabled={(seats || 1) >= 6}
                className="h-7 w-7 rounded-full bg-muted hover:bg-muted/80 flex items-center justify-center font-bold text-[14px] text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                aria-label="Increase seats"
              >
                +
              </button>
            </div>
          </div>
        </div>
      )}

      {/* EDEX MODAL PICKERS */}
      {openPicker && createPortal(
        <>
          <div
            className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={() => setOpenPicker(null)}
          />

          <div className="fixed inset-x-4 bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))] z-[101] mx-auto max-w-sm rounded-[24px] bg-card text-foreground p-5 shadow-2xl border border-border/60 animate-in slide-in-from-bottom-5 duration-200">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-border/40">
              <h3 className="text-[15px] font-extrabold text-foreground">
                {openPicker === "date" ? "Select Date" : "Select Departure Time"}
              </h3>
              <button
                type="button"
                onClick={() => setOpenPicker(null)}
                className="p-1.5 rounded-full hover:bg-muted text-muted-foreground transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* DATE PICKER POPUP */}
            {openPicker === "date" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between px-1">
                  <button
                    type="button"
                    onClick={handlePrevMonth}
                    disabled={isPrevMonthDisabled}
                    className={cn(
                      "p-1.5 rounded-full transition-colors cursor-pointer",
                      isPrevMonthDisabled ? "opacity-30 cursor-not-allowed text-muted-foreground" : "hover:bg-muted text-foreground"
                    )}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="text-[14px] font-black text-foreground">
                    {monthNames[currentMonth]} {currentYear}
                  </span>
                  <button
                    type="button"
                    onClick={handleNextMonth}
                    className="p-1.5 rounded-full hover:bg-muted text-foreground transition-colors cursor-pointer"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>

                <div className="grid grid-cols-7 text-center">
                  {daysOfWeek.map((d, idx) => (
                    <span key={idx} className="text-[10px] font-extrabold uppercase text-muted-foreground">
                      {d}
                    </span>
                  ))}
                </div>

                <div className="grid grid-cols-7 gap-1 text-center">
                  {calendarCells.map((day, idx) => {
                    if (day === null) return <div key={idx} className="h-8 w-8" />
                    const formattedMonth = currentMonth + 1 < 10 ? `0${currentMonth + 1}` : `${currentMonth + 1}`
                    const formattedDay = day < 10 ? `0${day}` : `${day}`
                    const cellDateStr = `${currentYear}-${formattedMonth}-${formattedDay}`
                    const isSelected = date === cellDateStr
                    const isPast = cellDateStr < effectiveMinDate
                    const isToday = cellDateStr === todayStr

                    if (isPast) {
                      return (
                        <div
                          key={idx}
                          className="h-8 w-8 rounded-full flex items-center justify-center font-bold text-[12px] mx-auto opacity-20 text-muted-foreground cursor-not-allowed"
                        >
                          {day}
                        </div>
                      )
                    }

                    return (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => handleSelectDay(day)}
                        className={cn(
                          "h-8 w-8 rounded-full flex items-center justify-center font-bold text-[12px] transition-all mx-auto cursor-pointer",
                          isSelected
                            ? "bg-[#C5FF00] text-black font-black shadow-xs scale-105"
                            : isToday
                              ? "border-2 border-[#C5FF00] font-black text-foreground bg-muted"
                              : "hover:bg-muted text-foreground"
                        )}
                      >
                        {day}
                      </button>
                    )
                  })}
                </div>

                <div className="pt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleClearDate}
                    className="flex-1 py-2.5 rounded-full border border-border/60 text-[13px] font-bold text-muted-foreground hover:bg-muted hover:text-foreground transition-all cursor-pointer"
                  >
                    Clear / Leave Blank
                  </button>
                </div>
              </div>
            )}

            {/* TIME PICKER POPUP */}
            {openPicker === "time" && (
              <div className="space-y-4 pt-1">
                {/* Selected Time Banner */}
                <div className="bg-muted/80 dark:bg-muted border border-border/60 rounded-[20px] p-3 text-center space-y-0.5">
                  <span className="text-[11px] font-extrabold uppercase tracking-wider text-muted-foreground">
                    Selected Departure Time
                  </span>
                  <div className="flex items-center justify-center gap-2">
                    <Clock className="h-5 w-5 text-foreground" />
                    <span className="text-[26px] font-black text-foreground tracking-tight">
                      {selectedHour}:{selectedMinute} {selectedAmPm}
                    </span>
                  </div>
                  {isCustomTimePast && (
                    <p className="text-[11.5px] font-bold text-destructive pt-0.5">
                      ⚠️ Selected time has already passed today
                    </p>
                  )}
                </div>

                {/* AM / PM Switcher */}
                <div className="space-y-1">
                  <span className="text-[11px] font-extrabold uppercase tracking-wider text-muted-foreground block px-1">
                    Period
                  </span>
                  <div className="grid grid-cols-2 gap-2 bg-muted p-1.5 rounded-[16px]">
                    <button
                      type="button"
                      onClick={() => setSelectedAmPm("AM")}
                      className={cn(
                        "py-2 rounded-[12px] font-extrabold text-[13px] transition-all cursor-pointer",
                        selectedAmPm === "AM"
                          ? "bg-[#C5FF00] text-black shadow-xs font-black"
                          : "text-muted-foreground hover:text-foreground font-bold"
                      )}
                    >
                      AM
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedAmPm("PM")}
                      className={cn(
                        "py-2 rounded-[12px] font-extrabold text-[13px] transition-all cursor-pointer",
                        selectedAmPm === "PM"
                          ? "bg-[#C5FF00] text-black shadow-xs font-black"
                          : "text-muted-foreground hover:text-foreground font-bold"
                      )}
                    >
                      PM
                    </button>
                  </div>
                </div>

                {/* Hours Grid */}
                <div className="space-y-1">
                  <span className="text-[11px] font-extrabold uppercase tracking-wider text-muted-foreground block px-1">
                    Hour
                  </span>
                  <div className="grid grid-cols-6 gap-1.5">
                    {HOURS.map((hStr) => {
                      const isSelected = selectedHour === hStr
                      const isPast = isHourPast(hStr)
                      return (
                        <button
                          key={hStr}
                          type="button"
                          disabled={isPast}
                          onClick={() => {
                            setSelectedHour(hStr)
                            const firstValidMin = MINUTES.find(m => !isTimeInPast(get24HourTimeStr(hStr, m, selectedAmPm)))
                            if (firstValidMin && isTimeInPast(get24HourTimeStr(hStr, selectedMinute, selectedAmPm))) {
                              setSelectedMinute(firstValidMin)
                            }
                          }}
                          className={cn(
                            "py-2 rounded-[12px] text-[13px] font-extrabold text-center transition-all",
                            isPast
                              ? "opacity-35 text-muted-foreground/60 bg-muted/40 border border-border/20 cursor-not-allowed pointer-events-none"
                              : isSelected
                              ? "bg-[#C5FF00] text-black font-black shadow-xs scale-105"
                              : "bg-card hover:bg-muted text-foreground border border-border/60 cursor-pointer"
                          )}
                        >
                          {hStr}
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Minutes Grid */}
                <div className="space-y-1">
                  <span className="text-[11px] font-extrabold uppercase tracking-wider text-muted-foreground block px-1">
                    Minute
                  </span>
                  <div className="grid grid-cols-6 gap-1.5">
                    {MINUTES.map((mStr) => {
                      const isSelected = selectedMinute === mStr
                      const isPast = isMinutePast(mStr)
                      return (
                        <button
                          key={mStr}
                          type="button"
                          disabled={isPast}
                          onClick={() => setSelectedMinute(mStr)}
                          className={cn(
                            "py-2 rounded-[12px] text-[13px] font-extrabold text-center transition-all",
                            isPast
                              ? "opacity-35 text-muted-foreground/60 bg-muted/40 border border-border/20 cursor-not-allowed pointer-events-none"
                              : isSelected
                              ? "bg-[#C5FF00] text-black font-black shadow-xs scale-105"
                              : "bg-card hover:bg-muted text-foreground border border-border/60 cursor-pointer"
                          )}
                        >
                          :{mStr}
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Actions */}
                <div className="pt-2 space-y-2">
                  <button
                    type="button"
                    disabled={isCustomTimePast}
                    onClick={handleConfirmCustomTime}
                    className={cn(
                      "w-full h-12 rounded-full font-black text-[15px] transition-all flex items-center justify-center gap-2 shadow-sm",
                      isCustomTimePast
                        ? "bg-muted text-muted-foreground cursor-not-allowed"
                        : "bg-[#C5FF00] text-black hover:opacity-90 cursor-pointer active:scale-[0.98]"
                    )}
                  >
                    Confirm {selectedHour}:{selectedMinute} {selectedAmPm}
                  </button>

                  <button
                    type="button"
                    onClick={handleClearTime}
                    className="w-full py-2.5 rounded-full border border-border/60 text-[13px] font-bold text-muted-foreground hover:bg-muted hover:text-foreground transition-all cursor-pointer"
                  >
                    Clear / Leave Blank
                  </button>
                </div>
              </div>
            )}

          </div>
        </>,
        document.body
      )}
    </div>
  )
}
