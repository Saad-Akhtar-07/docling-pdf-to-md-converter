const tableModes = ["accurate", "fast"];

function CheckboxRow({ id, label, checked, disabled, onChange }) {
  return (
    <label htmlFor={id} className="flex items-center justify-between gap-3 py-2">
      <span className="text-sm font-medium text-zinc-800">{label}</span>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-zinc-400 text-teal-700 focus:ring-teal-700"
      />
    </label>
  );
}

function SelectRow({ id, label, value, disabled, options, onChange }) {
  return (
    <label htmlFor={id} className="grid gap-1 py-2">
      <span className="text-sm font-medium text-zinc-800">{label}</span>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded border border-zinc-300 bg-white px-3 text-sm text-zinc-950 shadow-sm focus:border-teal-700 focus:outline-none focus:ring-1 focus:ring-teal-700 disabled:bg-zinc-100"
      >
        {options.map((option) => {
          const value = typeof option === "string" ? option : option.value;
          const label = typeof option === "string" ? option : option.label;

          return (
            <option key={value} value={value}>
              {label}
            </option>
          );
        })}
      </select>
    </label>
  );
}

function NumberRow({ id, label, value, disabled, min, step = 1, onChange }) {
  return (
    <label htmlFor={id} className="grid gap-1 py-2">
      <span className="text-sm font-medium text-zinc-800">{label}</span>
      <input
        id={id}
        type="number"
        min={min}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-10 rounded border border-zinc-300 bg-white px-3 text-sm text-zinc-950 shadow-sm focus:border-teal-700 focus:outline-none focus:ring-1 focus:ring-teal-700 disabled:bg-zinc-100"
      />
    </label>
  );
}

export default function ConversionOptions({ options, onChange, disabled }) {
  function updateOption(key, value) {
    onChange({ ...options, [key]: value });
  }

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-950">Conversion Options</h2>
      </div>
      <div className="grid gap-1 px-4 py-3">
        <CheckboxRow
          id="do-ocr"
          label="Enable OCR"
          checked={options.doOcr}
          disabled={disabled}
          onChange={(value) => updateOption("doOcr", value)}
        />
        <CheckboxRow
          id="force-ocr"
          label="Force visual OCR"
          checked={options.forceOcr}
          disabled={disabled}
          onChange={(value) => updateOption("forceOcr", value)}
        />
        <CheckboxRow
          id="do-table-structure"
          label="Extract tables"
          checked={options.doTableStructure}
          disabled={disabled}
          onChange={(value) => updateOption("doTableStructure", value)}
        />
        <SelectRow
          id="table-mode"
          label="Table mode"
          value={options.tableMode}
          disabled={disabled || !options.doTableStructure}
          options={tableModes}
          onChange={(value) => updateOption("tableMode", value)}
        />
        <CheckboxRow
          id="include-images"
          label="Include images"
          checked={options.includeImages}
          disabled={disabled}
          onChange={(value) => updateOption("includeImages", value)}
        />
        <NumberRow
          id="images-scale"
          label="Images scale"
          value={options.imagesScale}
          min={0.5}
          step={0.5}
          disabled={disabled || !options.includeImages}
          onChange={(value) => updateOption("imagesScale", value)}
        />
      </div>
    </section>
  );
}
