import { Plus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { JSONSchemaProperty } from '@/api';
import type { SchemaFormValue } from '@/components/form/SchemaForm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface ModelRow {
	name: string;
	label: string;
}

interface Props {
	/** Serialized rows — one `model_id | display name` pair per line. */
	value?: string;
	onChange: (v: string) => void;
}

function parse(value: string | undefined): ModelRow[] {
	return (value ?? '')
		.split('\n')
		.map((line) => {
			const [name, label] = line.split('|');
			return { name: (name ?? '').trim(), label: (label ?? '').trim() };
		})
		.filter((row) => row.name || row.label);
}

function serialize(rows: ModelRow[]): string {
	return rows
		.map((row) => {
			const name = row.name.trim();
			const label = row.label.trim();
			if (!name && !label) return '';
			return label ? `${name} | ${label}` : name;
		})
		.filter(Boolean)
		.join('\n');
}

/**
 * Structured editor for the custom credential's model list: one row per
 * model (id + optional display name), add/remove rows instead of typing
 * pipe-separated lines. The stored value stays the line format.
 */
export function ModelListEditor({ value, onChange }: Props) {
	const { t } = useTranslation();
	const [rows, setRows] = useState<ModelRow[]>(() => parse(value));
	// The last string we emitted (or received); an incoming value that
	// differs means the dialog reset the field, so re-parse.
	const lastSynced = useRef<string | undefined>(value);

	useEffect(() => {
		if (value !== lastSynced.current) {
			setRows(parse(value));
			lastSynced.current = value;
		}
	}, [value]);

	const emit = (next: ModelRow[]) => {
		setRows(next);
		const serialized = serialize(next);
		lastSynced.current = serialized;
		onChange(serialized);
	};

	const update = (index: number, patch: Partial<ModelRow>) => {
		emit(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
	};

	const remove = (index: number) => {
		emit(rows.filter((_, i) => i !== index));
	};

	return (
		<div className="flex flex-col gap-2">
			{rows.map((row, index) => (
				<div key={index} className="flex items-center gap-2">
					<Input
						value={row.name}
						onChange={(e) => update(index, { name: e.target.value })}
						placeholder={t('model-list-editor.name-placeholder')}
						className="flex-1"
					/>
					<Input
						value={row.label}
						onChange={(e) => update(index, { label: e.target.value })}
						placeholder={t('model-list-editor.label-placeholder')}
						className="flex-1"
					/>
					<Button
						variant="ghost"
						size="icon"
						onClick={() => remove(index)}
						aria-label={t('model-list-editor.remove')}
					>
						<X className="size-4 text-muted-foreground" />
					</Button>
				</div>
			))}
			<Button
				variant="outline"
				size="sm"
				className="w-fit"
				onClick={() => emit([...rows, { name: '', label: '' }])}
			>
				<Plus className="size-4" />
				{t('model-list-editor.add')}
			</Button>
		</div>
	);
}

/** `SchemaForm` `renderFor` hook: any field marked with
 *  `format: "model-list"` gets the structured row editor. */
export function modelListRenderFor(
	_key: string,
	prop: JSONSchemaProperty,
	value: SchemaFormValue,
	set: (v: SchemaFormValue) => void,
) {
	if (prop.format !== 'model-list') return undefined;
	return (
		<ModelListEditor
			value={value as string | undefined}
			onChange={(v) => set(v)}
		/>
	);
}
