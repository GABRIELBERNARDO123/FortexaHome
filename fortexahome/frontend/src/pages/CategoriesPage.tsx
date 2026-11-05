import {
  Archive,
  BookOpen,
  Briefcase,
  Car,
  Coffee,
  Gamepad2,
  Gift,
  GraduationCap,
  Heart,
  Home,
  LockKeyhole,
  PawPrint,
  Pencil,
  PiggyBank,
  Plane,
  Plus,
  Receipt,
  RotateCcw,
  Search,
  ShoppingBag,
  Smartphone,
  Tag,
  Trash2,
  TrendingUp,
  Utensils,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Panel,
  Select,
  Skeleton,
} from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { api, errorMessage } from "../lib/api";
import { useApiData } from "../lib/useApiData";
import type { Category } from "../types";

const ICONS: Record<string, LucideIcon> = {
  home: Home,
  utensils: Utensils,
  car: Car,
  heart: Heart,
  book: BookOpen,
  gamepad: Gamepad2,
  receipt: Receipt,
  "shopping-bag": ShoppingBag,
  paw: PawPrint,
  wallet: Wallet,
  "trending-up": TrendingUp,
  "piggy-bank": PiggyBank,
  tag: Tag,
  briefcase: Briefcase,
  plane: Plane,
  gift: Gift,
  "graduation-cap": GraduationCap,
  coffee: Coffee,
  smartphone: Smartphone,
  wrench: Wrench,
};

const ICON_OPTIONS = Object.keys(ICONS);

type CategoryKind = Category["kind"];
type StatusFilter = "" | "active" | "archived";
type KindFilter = "" | CategoryKind;

interface CategoryForm {
  name: string;
  kind: CategoryKind;
  color: string;
  icon: string;
}

function emptyForm(): CategoryForm {
  return { name: "", kind: "expense", color: "#ffa400", icon: "tag" };
}

export default function CategoriesPage() {
  const { auth } = useAuth();
  const isOwner = auth?.user.role === "owner";
  const { notify } = useToast();
  const categories = useApiData<Category[]>("/categories");
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState<KindFilter>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [form, setForm] = useState<CategoryForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Category | null>(null);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Category | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const visible = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("pt-BR");
    return (categories.data || []).filter((category) => {
      if (kindFilter && category.kind !== kindFilter) return false;
      if (statusFilter === "active" && category.archived) return false;
      if (statusFilter === "archived" && !category.archived) return false;
      return !term || category.name.toLocaleLowerCase("pt-BR").includes(term);
    });
  }, [categories.data, kindFilter, search, statusFilter]);

  const total = categories.data?.length || 0;
  const archivedCount = categories.data?.filter((category) => category.archived).length || 0;
  const inUseCount = categories.data?.filter((category) => category.in_use).length || 0;

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (category: Category) => {
    setEditing(category);
    setForm({
      name: category.name,
      kind: category.kind,
      color: category.color,
      icon: category.icon,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const closeModal = () => {
    if (saving) return;
    setModalOpen(false);
    setEditing(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        color: form.color,
        icon: form.icon,
      };
      if (editing) {
        await api(`/categories/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify("Categoria atualizada.");
      } else {
        await api("/categories", {
          method: "POST",
          body: JSON.stringify({ ...payload, kind: form.kind }),
        });
        notify("Categoria criada.");
      }
      setModalOpen(false);
      setEditing(null);
      categories.reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const confirmArchive = async () => {
    if (!archiveTarget) return;
    setArchiveLoading(true);
    try {
      await api(`/categories/${archiveTarget.id}`, {
        method: "PATCH",
        body: JSON.stringify({ archived: true }),
      });
      notify("Categoria arquivada. O histórico foi preservado.");
      setArchiveTarget(null);
      categories.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setArchiveLoading(false);
    }
  };

  const reactivate = async (category: Category) => {
    setActionId(category.id);
    try {
      await api(`/categories/${category.id}`, {
        method: "PATCH",
        body: JSON.stringify({ archived: false }),
      });
      notify("Categoria reativada.");
      categories.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setActionId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteLoading(true);
    try {
      await api(`/categories/${deleting.id}`, { method: "DELETE" });
      notify("Categoria excluída.");
      setDeleting(null);
      categories.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="ORGANIZAÇÃO"
        title="Categorias"
        description="Organize receitas e despesas, arquive o que não usa mais e preserve todo o histórico."
        actions={
          isOwner ? (
            <Button variant="primary" icon={Plus} onClick={openCreate}>
              Nova categoria
            </Button>
          ) : undefined
        }
      />

      {!isOwner ? (
        <div className="category-note">
          <LockKeyhole size={16} />
          <span>Você pode consultar as categorias da família. Apenas o responsável pela conta pode criar, editar ou arquivar.</span>
        </div>
      ) : null}

      <Panel className="section-panel">
        <div className="toolbar">
          <div className="search-box">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Buscar categoria..."
              aria-label="Buscar categoria"
            />
          </div>
          <Select
            aria-label="Filtrar por tipo de categoria"
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value as KindFilter)}
          >
            <option value="">Todos os tipos</option>
            <option value="expense">Despesas</option>
            <option value="income">Receitas</option>
          </Select>
          <Select
            aria-label="Filtrar por situação da categoria"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
          >
            <option value="">Todas as situações</option>
            <option value="active">Ativas</option>
            <option value="archived">Arquivadas</option>
          </Select>
        </div>
      </Panel>

      <Panel
        title="Categorias da família"
        subtitle={`${visible.length} exibida(s) de ${total} · ${archivedCount} arquivada(s) · ${inUseCount} em uso`}
      >
        {categories.loading ? (
          <Skeleton lines={7} />
        ) : categories.error ? (
          <ErrorState message={categories.error} onRetry={categories.reload} />
        ) : !visible.length ? (
          <EmptyState
            icon={Tag}
            title={total ? "Nada encontrado" : "Nenhuma categoria"}
            description={
              total
                ? "Ajuste a busca ou os filtros para encontrar a categoria desejada."
                : "Crie a primeira categoria para organizar a vida financeira da casa."
            }
            action={
              isOwner && !total ? (
                <Button variant="primary" icon={Plus} onClick={openCreate}>
                  Criar categoria
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="category-list">
            {visible.map((category) => {
              const Icon = ICONS[category.icon] || Tag;
              return (
                <article className="category-row" key={category.id}>
                  <span
                    className="category-swatch"
                    style={{
                      background: `color-mix(in srgb, ${category.color} 18%, transparent)`,
                      color: category.color,
                    }}
                  >
                    <Icon size={18} />
                  </span>
                  <div className="category-main">
                    <strong>{category.name}</strong>
                    <div className="category-meta">
                      <Badge tone={category.kind === "income" ? "good" : "warn"}>
                        {category.kind === "income" ? "Receita" : "Despesa"}
                      </Badge>
                      {category.is_system ? <Badge tone="brand">Padrão</Badge> : null}
                      {category.archived ? <Badge tone="neutral">Arquivada</Badge> : null}
                      <span className={category.in_use ? "usage in-use" : "usage"}>
                        {category.in_use
                          ? `Em uso em ${category.usage_count} registro(s)`
                          : "Sem uso"}
                      </span>
                    </div>
                  </div>
                  {isOwner ? (
                    <div className="row-actions category-actions">
                      <IconButton
                        label={`Editar categoria ${category.name}`}
                        icon={Pencil}
                        onClick={() => openEdit(category)}
                      />
                      {!category.is_system && !category.archived ? (
                        <IconButton
                          label={`Arquivar categoria ${category.name}`}
                          icon={Archive}
                          onClick={() => setArchiveTarget(category)}
                        />
                      ) : null}
                      {!category.is_system && category.archived ? (
                        <IconButton
                          label={`Reativar categoria ${category.name}`}
                          icon={RotateCcw}
                          disabled={actionId === category.id}
                          onClick={() => void reactivate(category)}
                        />
                      ) : null}
                      {!category.is_system ? (
                        <IconButton
                          label={`Excluir categoria ${category.name}`}
                          icon={Trash2}
                          disabled={category.in_use}
                          title={
                            category.in_use
                              ? "Categoria em uso. Arquive-a para preservar o histórico."
                              : undefined
                          }
                          onClick={() => setDeleting(category)}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </Panel>

      <Modal
        open={modalOpen}
        onClose={closeModal}
        title={editing ? "Editar categoria" : "Nova categoria"}
        subtitle={
          editing
            ? "Atualize o nome, a cor e o ícone. O tipo da categoria não pode ser alterado."
            : "Escolha um nome, o tipo e a identidade visual da categoria."
        }
        footer={
          <>
            <Button variant="ghost" onClick={closeModal} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="category-form" loading={saving}>
              {editing ? "Salvar categoria" : "Criar categoria"}
            </Button>
          </>
        }
      >
        <form id="category-form" onSubmit={submit} className="form-stack">
          <Field label="Nome da categoria">
            <Input
              required
              autoFocus
              maxLength={80}
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Ex.: Feira, Escola, Freelance..."
            />
          </Field>
          <div className="form-grid">
            <Field label="Tipo">
              <Select
                value={form.kind}
                disabled={Boolean(editing)}
                onChange={(event) => setForm({ ...form, kind: event.target.value as CategoryKind })}
              >
                <option value="expense">Despesa</option>
                <option value="income">Receita</option>
              </Select>
            </Field>
            <Field label="Ícone">
              <Select
                value={form.icon}
                onChange={(event) => setForm({ ...form, icon: event.target.value })}
              >
                {ICON_OPTIONS.map((icon) => (
                  <option key={icon} value={icon}>
                    {icon}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Cor" hint="Usada em gráficos e relatórios." className="span-2">
              <Input
                type="color"
                className="color-input"
                value={form.color}
                onChange={(event) => setForm({ ...form, color: event.target.value })}
              />
            </Field>
          </div>
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(archiveTarget)}
        title="Arquivar categoria?"
        description={`A categoria ${archiveTarget?.name || ""} deixa de aparecer em novos lançamentos, contas e orçamentos. O histórico e os registros existentes continuam intactos, e você pode reativá-la quando quiser.`}
        confirmLabel="Arquivar"
        loading={archiveLoading}
        onConfirm={() => void confirmArchive()}
        onClose={() => setArchiveTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Excluir categoria?"
        description={`A categoria ${deleting?.name || ""} será removida permanentemente. Só é possível excluir categorias sem nenhum registro vinculado.`}
        confirmLabel="Excluir"
        danger
        loading={deleteLoading}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
