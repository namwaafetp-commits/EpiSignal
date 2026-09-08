export const DISEASE_GROUP_OPTIONS = [
  { value: "all", label: "All disease groups" },
  { value: "respiratory", label: "Respiratory" },
  {
    value: "enteric_food_waterborne",
    label: "Enteric / food- & water-borne infections",
  },
  { value: "vector_borne", label: "Vector-borne infections" },
  { value: "vaccine_preventable", label: "Vaccine-preventable infections" },
  { value: "viral_hemorrhagic_fever", label: "Viral hemorrhagic fevers" },
  { value: "neurologic_invasive", label: "Neurologic / invasive infections" },
  {
    value: "blood_borne_sti",
    label: "Blood-borne / sexually transmitted infections",
  },
  {
    value: "healthcare_associated_amr",
    label: "Healthcare-associated / antimicrobial-resistant infections",
  },
  { value: "other_infectious", label: "Other infectious diseases" },
  { value: "unknown", label: "Unknown / unclassified" },
] as const;

export function diseaseGroupLabel(value: string | null | undefined): string {
  return (
    DISEASE_GROUP_OPTIONS.find((option) => option.value === value)?.label ??
    "Unknown / unclassified"
  );
}

export function hostSectorLabel(value: string | null | undefined): string {
  switch (value) {
    case "all":
      return "All";
    case "human":
      return "Human";
    case "animal":
      return "Animal";
    case "both":
      return "Human + Animal";
    default:
      return "Unknown";
  }
}
