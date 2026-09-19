/* Local research helper. Compile with a JDK; run with Productivity's own JVM
 * and lib/* classpath. No vendor JARs are distributed with laddercodec.
 */
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.lang.annotation.Annotation;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.jar.JarFile;
import javax.xml.namespace.QName;

public class InspectProductivity {
    static Map<String, Object> record(Object... items) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (int i = 0; i < items.length; i += 2) out.put((String) items[i], items[i + 1]);
        return out;
    }

    static Object value(Object v) throws Exception {
        if (v instanceof Class) return ((Class<?>) v).getName();
        if (v instanceof Enum) return ((Enum<?>) v).name();
        if (v instanceof Annotation) return annotation((Annotation) v);
        if (v != null && v.getClass().isArray()) {
            List<Object> list = new ArrayList<>();
            for (int i = 0; i < Array.getLength(v); ++i) list.add(value(Array.get(v, i)));
            return list;
        }
        return v;
    }

    static Map<String, Object> annotation(Annotation a) throws Exception {
        Map<String, Object> result = record("type", a.annotationType().getName());
        Method[] methods = a.annotationType().getDeclaredMethods();
        Arrays.sort(methods, Comparator.comparing(Method::getName));
        for (Method m : methods) result.put(m.getName(), value(m.invoke(a)));
        return result;
    }

    static List<Object> annotations(AnnotatedElement element) throws Exception {
        List<Object> result = new ArrayList<>();
        for (Annotation a : element.getDeclaredAnnotations()) {
            if (a.annotationType().getName().startsWith("jakarta.xml.bind."))
                result.add(annotation(a));
        }
        return result;
    }

    static Map<String, Object> describe(Class<?> type) throws Exception {
        List<Object> properties = new ArrayList<>();
        List<Object> fields = new ArrayList<>();
        List<Object> enums = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Class<?> c = type; c != null && c != Object.class; c = c.getSuperclass()) {
            Method[] methods = c.getDeclaredMethods();
            Arrays.sort(methods, Comparator.comparing(Method::toGenericString));
            for (Method m : methods) {
                if (m.isBridge() || m.isSynthetic() || !Modifier.isPublic(m.getModifiers())
                        || Modifier.isStatic(m.getModifiers()) || m.getParameterCount() != 0
                        || m.getReturnType() == void.class
                        || !(m.getName().startsWith("get") || m.getName().startsWith("is"))
                        || !seen.add(m.getName())) continue;
                String stem = m.getName().substring(m.getName().startsWith("is") ? 2 : 3);
                boolean writable;
                try { type.getMethod("set" + stem, m.getReturnType()); writable = true; }
                catch (NoSuchMethodException e) { writable = false; }
                List<String> constants = new ArrayList<>();
                if (m.getReturnType().isEnum()) {
                    for (Field f : m.getReturnType().getDeclaredFields())
                        if (f.isEnumConstant()) constants.add(f.getName());
                }
                properties.add(record("getter", m.getName(), "declared_in", c.getName(),
                    "return_type", m.getGenericReturnType().getTypeName(), "setter", writable,
                    "annotations", annotations(m), "enum_constants", constants));
            }
            for (Field f : c.getDeclaredFields()) {
                List<Object> attrs = annotations(f);
                if (!attrs.isEmpty()) fields.add(record("name", f.getName(),
                    "declared_in", c.getName(), "type", f.getGenericType().getTypeName(),
                    "annotations", attrs));
            }
            for (Class<?> nested : c.getDeclaredClasses()) {
                if (!nested.isEnum()) continue;
                List<String> constants = new ArrayList<>();
                for (Field f : nested.getDeclaredFields())
                    if (f.isEnumConstant()) constants.add(f.getName());
                enums.add(record("class", nested.getName(), "constants", constants));
            }
        }
        List<String> constructors = new ArrayList<>();
        for (Constructor<?> ctor : type.getConstructors()) constructors.add(ctor.toGenericString());
        Collections.sort(constructors);
        return record("class", type.getName(), "superclass", type.getSuperclass().getName(),
            "annotations", annotations(type), "constructors", constructors,
            "properties", properties, "annotated_fields", fields, "enums", enums);
    }

    static void inventory(Path jarPath, Path output) throws Exception {
        List<String> names = new ArrayList<>();
        try (JarFile jar = new JarFile(jarPath.toFile())) {
            jar.stream().map(e -> e.getName())
                .filter(n -> n.matches("com/adc/common/model/instruction/AdcInst_[^/$]+\\.class"))
                .forEach(n -> names.add(n.substring(0, n.length() - 6).replace('/', '.')));
        }
        Collections.sort(names);
        List<Object> instructions = new ArrayList<>();
        List<Object> errors = new ArrayList<>();
        for (String name : names) {
            try { instructions.add(describe(Class.forName(name, false,
                InspectProductivity.class.getClassLoader()))); }
            catch (Exception | LinkageError e) { errors.add(record("class", name, "error", e.toString())); }
        }
        Object report = record("instruction_count", names.size(), "instructions", instructions,
            "errors", errors, "scope", "Reflection metadata; defaults and serialization not inferred.");
        Class<?> builderClass = Class.forName("com.google.gson.GsonBuilder");
        Object builder = builderClass.getConstructor().newInstance();
        builderClass.getMethod("setPrettyPrinting").invoke(builder);
        Object gson = builderClass.getMethod("create").invoke(builder);
        String json = (String) Class.forName("com.google.gson.Gson")
            .getMethod("toJson", Object.class).invoke(gson, report);
        Files.writeString(output, json + "\n", StandardCharsets.UTF_8);
        System.out.println("Inspected " + instructions.size() + " instructions; " + errors.size() + " errors.");
        if (!errors.isEmpty()) throw new IllegalStateException("Inventory incomplete; inspect errors in output.");
    }

    static void serialize(String className, Path output) throws Exception {
        Class<?> type = Class.forName(className);
        Object instruction = type.getConstructor().newInstance();
        Class<?> contextClass = Class.forName("jakarta.xml.bind.JAXBContext");
        Object context = contextClass.getMethod("newInstance", String.class)
            .invoke(null, "com.adc.common.model:com.adc.common.model.instruction:com.adc.common.model.tag");
        Object marshaller = contextClass.getMethod("createMarshaller").invoke(context);
        Class<?> marshallerClass = Class.forName("jakarta.xml.bind.Marshaller");
        marshallerClass.getMethod("setProperty", String.class, Object.class)
            .invoke(marshaller, "jaxb.formatted.output", true);
        Class<?> wrapperClass = Class.forName("jakarta.xml.bind.JAXBElement");
        Object wrapper = wrapperClass.getConstructor(QName.class, Class.class, Object.class)
            .newInstance(new QName("instruction"), Object.class, instruction);
        try (ByteArrayOutputStream stream = new ByteArrayOutputStream()) {
            marshallerClass.getMethod("marshal", Object.class, OutputStream.class)
                .invoke(marshaller, wrapper, stream);
            Files.write(output, stream.toByteArray());
        }
        System.out.println("Serialized default " + className + " to " + output);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException(
            "inventory <productivity.jar> <output.json> | serialize <class> <output.xml>");
        if (args[0].equals("inventory")) inventory(Path.of(args[1]), Path.of(args[2]));
        else if (args[0].equals("serialize")) serialize(args[1], Path.of(args[2]));
        else throw new IllegalArgumentException("Unknown mode: " + args[0]);
    }
}
