"use client"

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <Tabs
      value={value}
      onValueChange={(next) => {
        const option = options.find((candidate) => candidate.value === next)
        if (option) onChange(option.value)
      }}
    >
      <TabsList aria-label={label} className="h-8 rounded-lg bg-secondary p-0.5">
        {options.map((option) => (
          <TabsTrigger
            key={option.value}
            value={option.value}
            className="rounded-md px-3 text-[13px] data-[state=active]:bg-background data-[state=active]:shadow-[var(--shadow-sm)]"
          >
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
